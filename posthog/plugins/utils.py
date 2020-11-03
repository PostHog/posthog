import io
import json
import os
import re
import tarfile
from typing import Dict, Optional
from zipfile import BadZipFile, ZipFile

import requests


def parse_github_url(url: str) -> Optional[Dict[str, str]]:
    match = re.search(
        r"^^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)((\/commit|\/tree|\/releases\/tag|\/archive)\/([A-Za-z0-9_.\-\/]+)(\.zip|\/tar.gz|)|)\/?$",
        url,
    )
    if match:
        parsed_url = {"type": "github", "user": match.group(1), "repo": match.group(2), "tag": match.group(5)}
        parsed_url["root_url"] = "https://github.com/{}/{}".format(parsed_url["user"], parsed_url["repo"])
        parsed_url["url"] = parsed_url["root_url"]
        if parsed_url["tag"]:
            parsed_url["url"] = "https://github.com/{}/{}/tree/{}".format(
                parsed_url["user"], parsed_url["repo"], parsed_url["tag"]
            )
        return parsed_url


def parse_npm_url(url: str) -> Optional[Dict[str, str]]:
    match = re.search(r"^https?:\/\/(?:www\.)?npmjs\.com\/package\/([a-z0-9_-]+)\/?(v\/([A-Za-z0-9_.-]+)\/?|)$", url)
    if match:
        parsed_url = {"type": "npm", "pkg": match.group(1), "version": match.group(3)}
        parsed_url["root_url"] = "https://www.npmjs.com/package/{}".format(parsed_url["pkg"])
        parsed_url["url"] = parsed_url["root_url"]
        if parsed_url["version"]:
            parsed_url["url"] = "https://www.npmjs.com/package/{}/v/{}".format(parsed_url["pkg"], parsed_url["version"])
        return parsed_url


def parse_url(url: str, get_latest: Optional[bool] = False) -> Optional[Dict[str, str]]:
    parsed_url = parse_github_url(url)
    if parsed_url:
        if get_latest and not parsed_url["tag"]:
            try:
                commits = requests.get(
                    "https://api.github.com/repos/{}/{}/commits".format(parsed_url["user"], parsed_url["repo"])
                ).json()
                if len(commits) > 0 and commits[0].get("html_url", None):
                    return parse_url(commits[0]["html_url"])
                raise
            except Exception:
                raise Exception("Could not get latest commit for: {}".format(parsed_url["url"]))
        else:
            return parsed_url

    parsed_url = parse_npm_url(url)
    if parsed_url:
        if get_latest and not parsed_url["version"]:
            try:
                details = requests.get("https://registry.npmjs.org/{}/latest".format(parsed_url["pkg"])).json()
                version = details["version"]
                return parse_url("https://www.npmjs.com/package/{}/v/{}".format(parsed_url["pkg"], version))
            except Exception:
                raise Exception("Could not get latest commit for: {}".format(parsed_url["url"]))
        else:
            return parsed_url

    raise Exception("Must be a Github Repository or NPM package URL!")


def download_plugin_archive(url: str, tag: str):
    parsed_url = parse_url(url)

    if parsed_url["type"] == "github":
        url = "https://github.com/{user}/{repo}/archive/{tag}.zip".format(
            user=parsed_url["user"], repo=parsed_url["repo"], tag=tag or parsed_url["tag"]
        )
    elif parsed_url["type"] == "npm":
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


def get_json_from_archive(archive: bytes, filename: str):
    try:
        zip_file = ZipFile(io.BytesIO(archive), "r")
        root_folder = zip_file.namelist()[0]
        file_path = os.path.join(root_folder, filename)
        try:
            with zip_file.open(file_path) as reader:
                return json.loads(reader.read())
        except KeyError:
            return None
    except BadZipFile:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            root_folder = "/".join(tar.getmembers()[0].name.split("/")[0:-1])
            file_path = os.path.join(root_folder, filename)
            json_bytes = tar.extractfile(file_path).read()
            return json.loads(json_bytes)
