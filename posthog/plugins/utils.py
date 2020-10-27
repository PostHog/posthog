import io
import json
import os
import re
from zipfile import ZipFile

import requests


def download_plugin_github_zip(repo: str, tag: str):
    url_template = "{repo}/archive/{tag}.zip"
    url = url_template.format(repo=re.sub("/$", "", repo), tag=tag)
    response = requests.get(url)
    if not response.ok:
        raise Exception("Could not download archive from GitHub")
    return response.content


def load_json_file(filename: str):
    try:
        with open(filename, "r") as reader:
            return json.loads(reader.read())
    except FileNotFoundError:
        return None


def load_json_zip_bytes(archive: bytes, filename: str):
    zip_file = ZipFile(io.BytesIO(archive), "r")
    return load_json_zip_file(zip_file, filename)


def load_json_zip_file(zip_file: ZipFile, filename: str):
    zip_root_folder = zip_file.namelist()[0]
    file_path = os.path.join(zip_root_folder, filename)
    try:
        with zip_file.open(file_path) as reader:
            return json.loads(reader.read())
    except KeyError:
        return None
