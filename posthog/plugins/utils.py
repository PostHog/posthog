import io
import json
import os
import re
import tarfile
from typing import Dict, Optional
from zipfile import BadZipFile, ZipFile

import requests


def parse_github_url(url: str, get_latest_if_none=False) -> Optional[Dict[str, str]]:
    url = url.strip("/")
    match = re.search(
        r"^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)((\/commit|\/tree|\/releases\/tag)\/([A-Za-z0-9_.\-\/]+))?$",
        url,
    )
    if not match:
        match = re.search(
            r"^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)((\/archive)\/([A-Za-z0-9_.\-\/]+)(\.zip|\.tar\.gz))?$",
            url,
        )
    if not match:
        return None
    parsed = {"type": "github", "user": match.group(1), "repo": match.group(2), "tag": match.group(5)}
    parsed["root_url"] = "https://github.com/{}/{}".format(parsed["user"], parsed["repo"])
    if get_latest_if_none and not parsed["tag"]:
        try:
            commits_url = "https://api.github.com/repos/{}/{}/commits".format(parsed["user"], parsed["repo"])
            commits = requests.get(commits_url).json()
            if len(commits) > 0 and commits[0].get("html_url", None):
                return parse_url(commits[0]["html_url"])
            raise
        except Exception:
            raise Exception("Could not get latest commit for: {}".format(parsed["root_url"]))
    if parsed["tag"]:
        parsed["tagged_url"] = "https://github.com/{}/{}/tree/{}".format(parsed["user"], parsed["repo"], parsed["tag"])
    return parsed


def parse_npm_url(url: str, get_latest_if_none=False) -> Optional[Dict[str, str]]:
    match = re.search(r"^https?:\/\/(?:www\.)?npmjs\.com\/package\/([a-z0-9_-]+)\/?(v\/([A-Za-z0-9_.-]+)\/?|)$", url)
    if not match:
        return None
    parsed = {"type": "npm", "pkg": match.group(1), "version": match.group(3)}
    parsed["root_url"] = "https://www.npmjs.com/package/{}".format(parsed["pkg"])
    if get_latest_if_none and not parsed["version"]:
        try:
            details = requests.get("https://registry.npmjs.org/{}/latest".format(parsed["pkg"])).json()
            return parse_url("https://www.npmjs.com/package/{}/v/{}".format(parsed["pkg"], details["version"]))
        except Exception:
            raise Exception("Could not get latest commit for: {}".format(parsed["url"]))
    if parsed["version"]:
        parsed["tagged_url"] = "https://www.npmjs.com/package/{}/v/{}".format(parsed["pkg"], parsed["version"])
    return parsed


def parse_url(url: str, get_latest_if_none=False) -> Dict[str, str]:
    parsed_url = parse_github_url(url, get_latest_if_none)
    if parsed_url:
        return parsed_url
    parsed_url = parse_npm_url(url, get_latest_if_none)
    if parsed_url:
        return parsed_url
    raise Exception("Must be a Github Repository or NPM package URL!")


# passing `tag` overrides whatever is in the URL
def download_plugin_archive(url: str, tag: Optional[str] = None):
    parsed_url = parse_url(url)

    if parsed_url["type"] == "github":
        if not (tag or parsed_url.get("tag", None)):
            raise Exception("No Github tag given!")
        url = "https://github.com/{user}/{repo}/archive/{tag}.zip".format(
            user=parsed_url["user"], repo=parsed_url["repo"], tag=tag or parsed_url["tag"]
        )
    elif parsed_url["type"] == "npm":
        if not (tag or parsed_url.get("version", None)):
            raise Exception("No NPM version given")
        url = "https://registry.npmjs.org/{pkg}/-/{pkg}-{version}.tgz".format(
            pkg=parsed_url["pkg"], version=tag or parsed_url["version"]
        )
    else:
        raise Exception("Unknown Repository Format")

    response = requests.get(url)
    if not response.ok:
        raise Exception("Could not download archive from {}".format(parsed_url["type"]))
    return response.content


def load_json_file(filename: str):
    try:
        with open(filename, "r") as reader:
            return json.loads(reader.read())
    except FileNotFoundError:
        return None


def get_json_from_zip_archive(archive: bytes, filename: str):
    zip_file = ZipFile(io.BytesIO(archive), "r")
    root_folder = zip_file.namelist()[0]
    file_path = os.path.join(root_folder, filename)
    try:
        with zip_file.open(file_path) as reader:
            return json.loads(reader.read())
    except KeyError:
        return None


def get_json_from_tgz_archive(archive: bytes, filename: str):
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        if tar.getmembers()[0].isdir():
            root_folder = tar.getmembers()[0].name
        else:
            root_folder = "/".join(tar.getmembers()[0].name.split("/")[0:-1])
        file_path = os.path.join(root_folder, filename)
        extracted_file = tar.extractfile(file_path)
        if not extracted_file:
            return None
        json_bytes = extracted_file.read()
        return json.loads(json_bytes)


def get_json_from_archive(archive: bytes, filename: str):
    try:
        return get_json_from_zip_archive(archive, filename)
    except BadZipFile:
        return get_json_from_tgz_archive(archive, filename)
