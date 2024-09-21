import argparse
import os
import shutil
import glob
import xml.etree.ElementTree as ET


# Increment this and run this file every time you make breaking changes to UDFs
# After running this, you have to copy the `user_defined_function.xml` file to the charts repo and deploy it
# After it goes out, it is safe to land the posthog repo code
# If deploys aren't seamless, look into movie the copy to clickhouse earlier in the deploy process
UDF_VERSION = 1

XML_CONFIG = "user_defined_function.xml"

format_version_string = lambda version: f"v{version}"
VERSION_STR = format_version_string(UDF_VERSION)
LAST_VERSION_STR = format_version_string(UDF_VERSION - 1)

augment_function_name = lambda name: f"{name}_{VERSION_STR}"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new version for UDF deployment.")
    parser.add_argument("-f", "--force", action="store_true", help="override existing directories")
    args = parser.parse_args()

    os.chdir("user_scripts")
    if args.force:
        shutil.rmtree(VERSION_STR)
    try:
        os.mkdir(VERSION_STR)
    except FileExistsError:
        if not args.force:
            raise FileExistsError(
                f"A directory already exists for this version at posthog/user_scripts/{VERSION_STR}. Did you forget to increment the version? If not, delete the folder and run this again, or run this script with a -f"
            )
    for file in glob.glob("*.py"):
        shutil.copy(file, VERSION_STR)

    base_xml = ET.parse(XML_CONFIG)

    if os.path.exists(LAST_VERSION_STR):
        last_version_xml = ET.parse(os.path.join(LAST_VERSION_STR, XML_CONFIG))
    else:
        last_version_xml = ET.parse(XML_CONFIG)

    last_version_root = last_version_xml.getroot()
    # We want to update the name and the command to include the version, and add it to last version
    for function in list(base_xml.getroot()):
        name = function.find("name")
        name.text = augment_function_name(name.text)
        command = function.find("command")
        command.text = f"{VERSION_STR}/{command.text}"
        last_version_root.append(function)

    last_version_xml.write(os.path.join(VERSION_STR, XML_CONFIG))

# TODO: Update Mapping
