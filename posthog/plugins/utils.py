import io
import json
import os
import re
import tarfile
from typing import Dict, Optional
from urllib.parse import parse_qs, quote
from zipfile import BadZipFile, ZipFile

import requests


def parse_github_url(url: str, get_latest_if_none=False) -> Optional[Dict[str, Optional[str]]]:
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
    parsed: Dict[str, Optional[str]] = {
        "type": "github",
        "user": match.group(1),
        "repo": match.group(2),
        "tag": match.group(5),
    }
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


def parse_gitlab_url(url: str, get_latest_if_none=False) -> Optional[Dict[str, Optional[str]]]:
    private_token = None
    if "?" in url:
        url, query = url.split("?")
        params = {k: v[0] for k, v in parse_qs(query).items()}
        private_token = params.get("private_token", None)

    url = url.strip("/")
    match = re.search(r"^https?:\/\/(?:www\.)?gitlab\.com\/([A-Za-z0-9_.\-\/]+)$", url)
    if not match:
        return None

    parsed: Dict[str, Optional[str]] = {
        "type": "gitlab",
        "project": match.group(1),
        "tag": None,
        "private_token": private_token,
    }

    if parsed["project"] is None:  # really just needed for mypy
        return None

    if "/-/" in parsed["project"]:
        project, path = parsed["project"].split("/-/")
        parsed["project"] = project
        parsed["tag"] = path.split("/")[1]

    parsed["root_url"] = "https://gitlab.com/{}{}".format(
        parsed["project"], "?private_token={}".format(private_token) if private_token else ""
    )

    if get_latest_if_none and not parsed["tag"]:
        try:
            commits_url = "https://gitlab.com/api/v4/projects/{}/repository/commits{}".format(
                quote(parsed["project"], safe=""), "?private_token={}".format(private_token) if private_token else ""
            )
            commits = requests.get(commits_url).json()
            if len(commits) > 0 and commits[0].get("web_url", None):
                web_url = commits[0]["web_url"]
                if private_token:
                    web_url += "?private_token={}".format(private_token)
                return parse_gitlab_url(web_url)
            raise
        except Exception:
            raise Exception("Could not get latest commit for: {}".format(parsed["root_url"]))

    if parsed["tag"]:
        parsed["tagged_url"] = "https://gitlab.com/{}/-/tree/{}{}".format(
            parsed["project"], parsed["tag"], "?private_token={}".format(private_token) if private_token else ""
        )

    return parsed


def parse_npm_url(url: str, get_latest_if_none=False) -> Optional[Dict[str, Optional[str]]]:
    match = re.search(r"^https?:\/\/(?:www\.)?npmjs\.com\/package\/([a-z0-9_-]+)\/?(v\/([A-Za-z0-9_.-]+)\/?|)$", url)
    if not match:
        return None
    parsed: Dict[str, Optional[str]] = {"type": "npm", "pkg": match.group(1), "version": match.group(3)}
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


def parse_url(url: str, get_latest_if_none=False) -> Dict[str, Optional[str]]:
    parsed_url = parse_github_url(url, get_latest_if_none)
    if parsed_url:
        return parsed_url
    parsed_url = parse_npm_url(url, get_latest_if_none)
    if parsed_url:
        return parsed_url
    parsed_url = parse_gitlab_url(url, get_latest_if_none)
    if parsed_url:
        return parsed_url
    raise Exception("Must be a GitHub/GitLab repository or npm package URL!")


# passing `tag` overrides whatever is in the URL
def download_plugin_archive(url: str, tag: Optional[str] = None):
    parsed_url = parse_url(url)

    if parsed_url["type"] == "github":
        if not (tag or parsed_url.get("tag", None)):
            raise Exception("No GitHub tag given!")
        url = "https://github.com/{user}/{repo}/archive/{tag}.zip".format(
            user=parsed_url["user"], repo=parsed_url["repo"], tag=tag or parsed_url["tag"]
        )
    elif parsed_url["type"] == "gitlab":
        url_tag = tag or parsed_url.get("tag", None)
        url_project = parsed_url["project"]
        if not url_tag or not url_project:
            raise Exception("No GitLab tag or project given!")

        if parsed_url.get("private_token", None):
            url = "https://gitlab.com/api/v4/projects/{project}/repository/archive.zip?sha={tag}&private_token={token}".format(
                project=quote(url_project, safe=""), tag=url_tag, token=parsed_url["private_token"]
            )
        else:
            url = "https://gitlab.com/{project}/-/archive/{tag}/{repo}-{tag}.zip".format(
                project=url_project, repo=url_project.split("/")[-1], tag=url_tag
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
