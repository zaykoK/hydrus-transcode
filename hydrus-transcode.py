import os
import glob
import hydrus_api
import subprocess
import argparse

###################################################################
############ CONFIG SECTION - THIS IS WHERE YOU CAN CHANGE STUFF ##
###################################################################
# All config values should be specified in code format as in
# ex. TRANSCODE_NAMESPACE = "original" => is correct
#     TRANSCODE_NAMESPACE = original  => is not and will give you error
# For True/False statements remember about Upper case first letter
####################################################################
# This is the namespace you want to use for holding hash tag of original file
# This will get saved as <TRANSCODE_NAMESPACE>:<hash of original file> in specified tag repository
TRANSCODE_NAMESPACE = 'original'
# This is name of file service you want to use for holding transcoded version of files
# It is very strongly recommended to use a separate one from your main one
TRANSCODE_FILE_SERVICE = 'web-transcodes'
# This is name of tag service you want to use for holding hash tags
TRANSCODE_TAG_SERVICE = 'Imported Tags'
# Setting this to true will always re-encode and overwrite all the given files
# Should really only be used when changing settings of encoding, as it will allow for quick replace of all files
OVERWRITE_EXISTING_FILES=False
# Your API access key
HYDRUS_ACCESS_KEY = ''
####################
# Paths to folders #
####################
# This is the path to the folder where hydrus stores files
# This needs to be given without last backslash => '/path/to/the/folder'
HYDRUS_DATA_PATH = ''
# This is location of output of conversion
# For most automation you can add this folder as import folder to hydrus
CONVERSION_OUTPUT_PATH = './converted'
# Those are default settings
class ImageSettings:
    # Quality of encoding, for good quality to size ratio values of 50-75 recommended for webp, higher values give higher quality
    quality = 50
    # Output file type, right now this doesn't do anything, I plan to look into AVIF encoding, or maybe leave with png/jpeg ones as well
    type = 'webp'
    # Whether files should get resized
    resize = True
    # Max dimensions for files after resize
    # This should stay
    width = 1920
    height = 1920
class VideoSettings:
    # This by default represents CRF value, which to get good quality 1080p video is recommended to be kept around 30-36, lower values give better quality
    quality = 35
    codec = 'libvpx-vp9'
    type = 'webm'
    resize = True
    width = 1280
    height = 1280
    # Those values are duration of video file in seconds
    # They server a purpose of filtering
    # Files shorter than min_duration won't get converted
    # Files longer than max_duration won't get converted
    min_duration = 0 #seconds
    max_duration = 60 #seconds


IMAGE_SETTINGS_JPG = ImageSettings()
IMAGE_SETTINGS_JPG.quality = 50
IMAGE_SETTINGS_PNG = ImageSettings()
# In case of gifs it might be necessary to use
IMAGE_SETTINGS_GIF = ImageSettings()
VIDEO_SETTINGS_GIF = VideoSettings()
VIDEO_SETTINGS_GIF.type = 'webp'



##################################################################################
# I don't see option to not log the file deletion, which I assume means that if for whatever reason you might want the old one it will not import it without some shenanings inside hydrus itself

# IDEA #2 - Transcode service
# Run a permanent "service" that will under some given settings query hydrus every now and then like this
# Give me all files with 'x' search result
# Check if all of them have their transcode
# If some don't get them and transcode

# Maybe having a little "tracking option" would also work
# Where After searching for transcodes it searches originals whether they have info tag like transcode:<hash>
# If not add it, if yes check for correctness, this would maybe simplify some operations as additional searches would not be necessary

####### END OF CONFIG SECTION ####################################################
####### Code below shouldn't be modified if you have no idea what you are doing ##
##################################################################################

client = hydrus_api.Client()
client.access_key = HYDRUS_ACCESS_KEY
total_bytes_saved = 0
setting_do_cleanup = False
setting_do_search = False
setting_search_arguments=[]
setting_skip_movies=False



def find_file_in_data(file_hash):
    file_path = f"{HYDRUS_DATA_PATH}/f{file_hash[0:2]}/{file_hash}"
    files = glob.glob(f'{file_path}*')
    if len(files) > 1:
        print(f'Something went really wrong, there should be only 1 file with a hash name. For safety aborting.')
        print(f'Problematic file : {files}')
    else:
        return files[0]  # There should be only one file

def convert_using_magick(path: str, options: ImageSettings, hash: str):
    global total_bytes_saved
    #arguments = f'-quality {options.quality} -define {options.type} -resize {options.width}x{options.height}\>'
    output_path = f'{CONVERSION_OUTPUT_PATH}/{hash}.{options.type}'
    #command = f'magick {path} {arguments} {output_path}'
    #return_code = os.system(command)
    return_code = subprocess.run(['magick',path,'-quality',str(options.quality),'-define',str(options.type),'-resize',f'{options.width}x{options.height}\>', output_path],capture_output=True,text=True)
    if return_code.returncode != 0:
        print(f'Conversion error on {path}')
        input()  # Waiting for user input

    #Calculate savings if any
    original_size = os.stat(path).st_size
    transcoded_size = os.stat(output_path).st_size
    difference = original_size - transcoded_size
    total_bytes_saved += difference

    print(f'File smaller by {(difference) / 1024}KB')

    return output_path

def get_video_file_info(path):
    # This is of course slightly naive as it only gets video 0 size, but it works for me
    ffprobe_process = subprocess.run(['ffprobe', '-v', 'error', '-select_streams' ,'v:0', '-show_entries', 'format=duration : stream=width,height', '-of' ,'csv=s=x:p=0' ,f'{path}'],capture_output=True,text=True)
    size = ffprobe_process.stdout.strip()
    #print(size)
    line_split = size.split('\n')
    duration = line_split[1]
    splitted=line_split[0].split('x')
    width = splitted[0]
    height = splitted[1]
    print(f"Duration:{duration}")
    print(f'Width:{width}\nHeight:{height}')
    return [width,height],duration

def convert_using_ffmpeg(path: str, options: VideoSettings,hash:str):
    # Given how videos are working on the web, video conversion really only make sense for videos that are too large in bit rate or resolution for mostly mobile devices to decode
    # From what i found, mobile phones usually decode video up to their screen size (not really true, mine can do 4k playback, problems really seem to start when kinda going above it as in 2550x3500 etc.), anyway this conversion should only happen when I find something that might make playback problematic for mobile
    # Which is going to boil down to resolution, bitrate (as too large bitrate won't work as wifi streaming) and video encoded in some old/weird encoders that might not work
    global setting_skip_movies
    if setting_skip_movies:
        return
    dimensions,duration = get_video_file_info(path)
    if float(duration) < options.min_duration or float(duration) > options.max_duration:
        print(f'Duration of file {hash} outside of options, skipping.')
        return
    # This makes sure that aspect ratio is kept
    resize_settings=f'{options.width}:-1'
    if dimensions[0] < dimensions[1]:
        resize_settings=f'-1:{options.height}'

    scale = ['','']
    if options.resize:
        if options.height < int(dimensions[1]) or options.width < int(dimensions[0]):
            print(f'Desired resolution lower than original size. Re-encoding.')
            scale=["-vf",f"scale={resize_settings}"]
    
    subprocess.run(['ffmpeg','-i',path,'-c:v',options.codec,'-b:v','0','-crf',str(options.quality),'-row-mt','1',scale[0],scale[1],f'{CONVERSION_OUTPUT_PATH}/{hash}.{options.type}'],capture_output=True,text=True)

#This checks for existance of transcoded file
def check_for_existence(hash:str):
    tag = f"{TRANSCODE_NAMESPACE}:{hash}"
    files = client.search_files([tag],file_service_name=TRANSCODE_FILE_SERVICE,tag_service_name=TRANSCODE_TAG_SERVICE,return_hashes=True)
    if len(files) > 1:
        print(f"Multiple files exist for {hash}:")
        for file in files:
            print(f"There exist a transcoded file for {hash} its hash = {file}")
        return files
    if len(files) == 1:
        print(f"There exist a transcoded file for {hash} its hash = {files[0]}")
        return files
    if len(files) == 0:
        print('No transcoded files found')
        return []

def check_for_original(hashes:list[str]):
    #Get metadata for given hashes
    responses = client.get_file_metadata(hashes=hashes)
    files_counter_exist = 0
    files_counter_deleted = 0
    files_counter = 0
    responses_length = len(responses)
    for response in responses:
        #Get tags from the response
        tags:list[str] = get_tags_from_response(response)
        #Check if there is a original:<hash> tag in the entries
        original = ''
        for tag in tags:
            if f'{TRANSCODE_NAMESPACE}:' in tag:
                original = tag.removeprefix(f'{TRANSCODE_NAMESPACE}:')
                #print(original)
        #get hash of the transcoded file
        hash = response.get("hash")
        print (f"Processing file :{hash}. {files_counter}/{responses_length}.", end="\r")

        #Display whether or not there is a file associated with transcoded one
        #print(f"{hash} = {original}")
        #If there is
        if (original != ""):
            #Search for that file
            original_file = client.search_files([f"system:hash = {original}"],return_hashes=True)

            # The only thing I should ever get back from above search is either a single hash or nothing
            if len(original_file) == 1:
                #print(f"Original file for {hash} still exists")
                files_counter_exist += 1
            else:
                files_counter_deleted += 1
                #print(f"Original file for {hash} is deleted.")
                #This is where Deletion should happen
                print(f"Deleting {hash}.")
                client.delete_files(hashes=[hash],file_service_name=TRANSCODE_FILE_SERVICE,reason="[cleanup] deleted original file")
        files_counter += 1
    print (f"Found {len(responses)} files.\n{files_counter_deleted}/{responses_length} deleted.\n{files_counter_exist}/{responses_length} kept.")

# This deletes transcoded files for files that don't exist anymore
def cleanup_procedure():
    #Search for files having transcode original namespace
    search_response = client.search_files(tags=[f'{TRANSCODE_NAMESPACE}:*'],file_service_name=TRANSCODE_FILE_SERVICE,tag_service_name=TRANSCODE_TAG_SERVICE,return_hashes=True)
    check_for_original(search_response)

def get_tags_from_response(response):
    services = response.get("service_names_to_statuses_to_display_tags")
    tags = services.get(TRANSCODE_TAG_SERVICE).get('0')
    return tags

def convert_file(file_path: str, hash: str):
    split = os.path.splitext(file_path)
    fileName = split[0]
    extension = split[1]

    # Add a check for some minimum settings, so for example 2 hour video doesn't start getting converted as it will take loooong time and probably given how videos like that are, this conversion will look worse and be bigger in size anyway
    # Proposed criteria
    # 1. Very large/long video files - maybe I'll find a way to get video length or amount of frames or something
    # 2. Images and videos (especially videos) that are already small in size/resolution (criteria needed)
    # 2a. For images probably anything below wanted resolution although reducing a 1080p png still gives huge reduction in file size
    # Might be interesting to create demo reel/preview kind of thing for long videos, or maybe literally do some sort of youtube like thing where a 360p/480p/720p could be done - as on a phone a lot of times a 480p video (heavily compressed or not) is not that noticably different from a 720p/1080p, unless you really start looking into the details
    # This obviously require additional support in hydrus-react to have this sort of functionality, and a some edits into philosophy of how I handle recognizing the transcodes


    if extension in ('.jpg', '.jpeg'):
        converted_file = convert_using_magick(file_path, IMAGE_SETTINGS_JPG, hash)

    if extension in ('.png'):
        converted_file = convert_using_magick(file_path, IMAGE_SETTINGS_PNG, hash)

    if extension in ('.gif'):
        # Large gifs > 50MB (This limit is arbitrary) should probably be converted using ffmpeg as magick tend to crash with them
        if os.stat(file_path).st_size > 50000 * 1024:
            print(f"Should be using ffmpeg because file is bigger than 50MB : {os.stat(file_path).st_size / (1024*1024)}MB")
            converted_file = convert_using_ffmpeg(file_path, VIDEO_SETTINGS_GIF, hash)
        else:
            converted_file = convert_using_magick(file_path, IMAGE_SETTINGS_GIF, hash)
    if extension in ('.webm,.mp4,.avi,.mkv'):
        #print(f'Doing video conversion on {file_path} to {fileName}.webp')
        converted_file = convert_using_ffmpeg(file_path, VideoSettings(), hash)
    if converted_file:
        add_file(converted_file,hash)
    
def add_file(path,hash):
    return
    # Right now it's impossible to add a file to a specific file repo, so this is more of a future thing right now
    #print(f'Adding file :{path}, with hash "{TRANSCODE_NAMESPACE}:{hash}"')
    #client.add_and_tag_files([path],f"{TRANSCODE_NAMESPACE}:{hash}",service_names=[TRANSCODE_TAG_SERVICE])

class ServiceInfo:
    def __init__(self,new_name:str,new_key:str):
        self.name:str = new_name
        self.service_key:str = new_key
    def __str__(self):
        return f"{self.name}:{self.service_key} \n"

class ServicesInfo:
    tags_services:list[ServiceInfo] = []
    file_services:list[ServiceInfo] = []

    def __str__(self):
        tags_string:str = ''
        tags_string += "Tag Services: \n"
        for entry in self.tags_services:
            tags_string += str(entry)
        tags_string += "File Services: \n"
        for entry in self.file_services:
            tags_string += str(entry)
        return tags_string

def get_services():
    response = client.get_services()
    #print(response)
    if response:
        tag_services = response.get('local_tags')
        #print(tag_services)
        for tag_service in tag_services:
            name = tag_service.get('name')
            key = tag_service.get('service_key')
            service = ServiceInfo(name,key)
            services_info.tags_services.append(service)
        file_services = response.get('local_files')
        for file_service in file_services:
            name = file_service.get('name')
            key = file_service.get('service_key')
            service = ServiceInfo(name,key)
            services_info.file_services.append(service)
        #print(services_info)

def check_config():
    #Check if if file services available
    file_service_correct = False
    tag_service_correct = False
    for file_service in services_info.file_services:
        if file_service.name == TRANSCODE_FILE_SERVICE:
            file_service_correct = True
    for tag_service in services_info.tags_services:
        if tag_service.name == TRANSCODE_TAG_SERVICE:
            tag_service_correct = True
    # Check permissions
    # Check data folder
    data_folder_correct = True
    data_folder = os.listdir(f"{HYDRUS_DATA_PATH}/")
    if len(data_folder) != 256:
        print('Supplied hydrus data folder might not be correct')
        data_folder_correct = False
    conversion_folder_exist=os.path.exists(CONVERSION_OUTPUT_PATH)
    
    if (conversion_folder_exist == False):
        print(f"Conversion folder doesn't exist trying to make new.")
        os.mkdir(CONVERSION_OUTPUT_PATH)
        conversion_folder_exist=os.path.exists(CONVERSION_OUTPUT_PATH)
    # Check if converter programs are callable, those checks are quite naive but will at least give some form of safety as to whether you can run them through this script
    magick_correct = False
    ffmpeg_correct = False
    # Magick
    code = subprocess.run('magick',capture_output=True)
    if (code.returncode == 0):
        magick_correct = True
        #print('Found magick')
    # ffmpeg
    code = subprocess.run('ffmpeg',capture_output=True)
    if (code.returncode == 1):
        ffmpeg_correct = True
        #print('Found ffmpeg')

    return file_service_correct and tag_service_correct and data_folder_correct and magick_correct and ffmpeg_correct

def get_current_transcodes() -> list[list[str],list[str]]:
    #This returns all files in transcode file repo having <transcode_namespace>:<hash> tags
    transcodes = client.search_files([f'{TRANSCODE_NAMESPACE}:*'],file_service_name=TRANSCODE_FILE_SERVICE,return_hashes=True)
    #Now for all of them grab all the originals they link to
    meta_responses = client.get_file_metadata(transcodes)
    originals = []
    hashes = []
    # For each of responses grab their original tag
    for response in meta_responses:
        tags:list[str] = get_tags_from_response(response)
        #Check if there is a original:<hash> tag in the entries
        hash = response.get('hash')
        original = ''
        for tag in tags:
            if f'{TRANSCODE_NAMESPACE}:' in tag:
                original = tag.removeprefix(f'{TRANSCODE_NAMESPACE}:')
                originals.append(original)
                hashes.append(hash)
    return originals,hashes
        
def start_conversion(hashes:list[str]):
    # Add a check for existance of transcode for a given a hash and a option whether or not to overwrite it
    files_that_have_transcodes,transcode_hashes = get_current_transcodes()
    #return
    counter = 0
    # Run for every file found
    for hash in hashes:
        should_convert = True

        # TODO This makes sense logically but will require a change to something that is not O(n) in complexity
        # Probably some sort of hash/map where I will just check for existance of a key, dictionary is a candidate for this

        # If file has a transcode, check if we are overwriting it, if yes send to transcode, if not set for skipping
        if hash in files_that_have_transcodes:
            #print(f'{hash} already has transcode : {transcode_hashes[files_that_have_transcodes.index(hash)]}')
            if OVERWRITE_EXISTING_FILES:
                should_convert = True
                # Check whether file exists
                existing_files = check_for_existence(hash)
                # for each file associated delete them
                print(f"Deleting {existing_files}")
                client.delete_files(hashes=[existing_files],file_service_name=TRANSCODE_FILE_SERVICE,reason="[cleanup] deleted original file")
            else:
                should_convert = False
        if should_convert:
            path = find_file_in_data(hash)
            # print(f"Path resolved to :{path}")
            convert_file(path, hash)
            print(f'Done with file {counter}/{len(hashes)}')
        else:
            print(f'File {hash} has transcoded version, skipping.')
        counter += 1

    print(f"Right now it's impossible(?) to push converted files using api to specified file repository. Manual import required. Recommended using a import folder for now. You can set up all the import options there.")

def resolve_arguments():
    global setting_do_cleanup
    global setting_do_search
    global setting_search_arguments
    global setting_skip_movies
    global OVERWRITE_EXISTING_FILES
    parser = argparse.ArgumentParser(description="Hydrus-transcode automates transcoding process for hydrus files. This program requires understanding of what you want to achieve. Before usage make sure that configuration (At the top of this file) is correct for your instance, otherwise program might not run (best case scenario) or might delete every file in your hydrus instance (worst case). Thread carefully.")
    parser.add_argument('--skip_movies',action='store_true',help='Skips transcoding of movie files.')
    parser.add_argument('--overwrite',action='store_true',help='Forces overwriting of existing transcode files regardless of settings.')
    parser.add_argument('--cleanup',action='store_true',help='Runs a cleanup routine, deleting every transcoded file for which th original was deleted. If specified with --search it will run cleanup first, then search.')
    parser.add_argument('--search',nargs='*',default=[],help='Runs a search and convert for given search. Ex. "--search "creator:leonardo da-vinci" "character:mona lisa" " will convert every possible file matching criteria')
    arguments = parser.parse_args()
    if (arguments.cleanup == True):
        setting_do_cleanup =True
    if (arguments.skip_movies):
        print('Skipping Movies')
        setting_skip_movies=True
    if (arguments.overwrite):
        OVERWRITE_EXISTING_FILES=True
    if (arguments.search):
        setting_do_search = True
        split_search = arguments.search
        setting_search_arguments = split_search
    if not (arguments.search or arguments.cleanup):
        parser.print_help()
        
     
services_info = ServicesInfo()

def main():
    resolve_arguments()
    get_services()
    config_correct = check_config()
    if config_correct:
        if setting_do_cleanup:
            print('Do a cleanup pass')
            cleanup_procedure()
        if setting_do_search:
            print (f'Do a search and convert for {setting_search_arguments}')
            results = client.search_files(setting_search_arguments, return_hashes=True)
            print(f"Found {len(results)} files. Starting transcoding process.")
            start_conversion(results)

            # client.add_and_tag_files()
            if total_bytes_saved/(1024*1024) > 1024:
                print(f"Total size save: {round(total_bytes_saved/(1024*1024*1024),2)}GB")
            if total_bytes_saved/1024 > 1024:
                print(f"Total size save: {round(total_bytes_saved/(1024*1024),2)}MB")
            else:
                print(f"Total size save: {round(total_bytes_saved/1024,2)}KB")
    else:
        print('There was an error with parsing config. Aborting...')


main()
