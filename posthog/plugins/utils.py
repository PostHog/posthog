import io
import os
import re
import json
import tarfile
from tarfile import ReadError
from typing import Any, Optional
from urllib.parse import parse_qs, quote
from zipfile import ZIP_DEFLATED, BadZipFile, Path, ZipFile

from django.conf import settings

import requests


def parse_github_url(url: str, get_latest_if_none=False) -> Optional[dict[str, Optional[str]]]:
    url, private_token = split_url_and_private_token(url)
    match = re.search(
        r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(/(commit|tree|releases/tag)/([A-Za-z0-9_.\-]+)/?([A-Za-z0-9_.\-/]+)?)?$",
        url,
    )
    if not match:
        # we include an empty group () to default the path to '' while keeping the number of groups the same
        match = re.search(
            r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(/(archive)/([A-Za-z0-9_.\-/]+)(?:\.zip|\.tar\.gz)())?$",
            url,
        )
    if not match:
        return None

    parsed: dict[str, Optional[str]] = {
        "type": "github",
        "root_url": f"https://github.com/{match.group(1)}/{match.group(2)}",
        "user": match.group(1),
        "repo": match.group(2),
        "ref_type": match.group(4),
        "tag": match.group(5),
        "path": match.group(6) or None,
        "private_token": private_token,
    }

    if get_latest_if_none and parsed["ref_type"] not in ("commit", "archive"):
        token = private_token or settings.GITHUB_TOKEN
        headers = {"Authorization": "Bearer {}".format(token)} if token else {}

        try:
            if parsed["ref_type"] == "releases/tag":
                parsed["tag"] = "refs/tags/{}".format(parsed["tag"])
            elif not re.match(r"^[a-f0-9]{40}$", parsed["tag"] or ""):
                commits_url = "https://api.github.com/repos/{}/{}/commits?sha={}&path={}".format(
                    parsed["user"],
                    parsed["repo"],
                    parsed["tag"] or "",
                    parsed["path"] or "",
                )
                commits = requests.get(commits_url, headers=headers).json()

                if isinstance(commits, dict):
                    raise Exception(commits.get("message"))
                if len(commits) > 0 and commits[0].get("sha", None):
                    parsed["tag"] = commits[0]["sha"]
                else:
                    raise Exception(f"Could not find a commit with a hash in {commits}")

        except Exception as e:
            raise Exception(f"Could not get latest commit for {parsed['root_url']}. Reason: {e}")

    if parsed["tag"]:
        parsed["tagged_url"] = "https://github.com/{}/{}/tree/{}{}{}".format(
            parsed["user"],
            parsed["repo"],
            parsed["tag"],
            "/" + parsed["path"] if parsed["path"] else "",
            "?private_token={}".format(private_token) if private_token else "",
        )

    return parsed


def parse_gitlab_url(url: str, get_latest_if_none=False) -> Optional[dict[str, Optional[str]]]:
    url, private_token = split_url_and_private_token(url)
    match = re.search(r"^https?://(?:www\.)?gitlab\.com/([A-Za-z0-9_.\-/]+)$", url)
    if not match:
        return None

    parsed: dict[str, Optional[str]] = {
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
        parsed["project"],
        "?private_token={}".format(private_token) if private_token else "",
    )

    if get_latest_if_none and not parsed["tag"]:
        try:
            token = private_token or settings.GITLAB_TOKEN
            headers = {"Authorization": "Bearer {}".format(token)} if token else {}
            commits_url = "https://gitlab.com/api/v4/projects/{}/repository/commits".format(
                quote(parsed["project"], safe="")
            )
            commits = requests.get(commits_url, headers=headers).json()
            if len(commits) > 0 and commits[0].get("id", None):
                parsed["tag"] = commits[0]["id"]
            else:
                raise
        except Exception:
            raise Exception("Could not get latest commit for: {}".format(parsed["root_url"]))

    if parsed["tag"]:
        parsed["tagged_url"] = "https://gitlab.com/{}/-/tree/{}{}".format(
            parsed["project"],
            parsed["tag"],
            "?private_token={}".format(private_token) if private_token else "",
        )

    return parsed


def parse_npm_url(url: str, get_latest_if_none=False) -> Optional[dict[str, Optional[str]]]:
    url, private_token = split_url_and_private_token(url)
    match = re.search(
        r"^https?://(?:www\.)?npmjs\.com/package/([@a-z0-9_-]+(/[a-z0-9_-]+)?)?/?(v/([A-Za-z0-9_.-]+)/?|)$",
        url,
    )
    if not match:
        return None
    parsed: dict[str, Optional[str]] = {
        "type": "npm",
        "pkg": match.group(1),
        "tag": match.group(4),
        "private_token": private_token,
    }

    parsed["root_url"] = "https://www.npmjs.com/package/{}{}".format(
        parsed["pkg"],
        "?private_token={}".format(private_token) if private_token else "",
    )
    if get_latest_if_none and not parsed["tag"]:
        try:
            token = private_token or settings.NPM_TOKEN
            headers = {"Authorization": "Bearer {}".format(token)} if token else {}
            details = requests.get(
                "https://registry.npmjs.org/{}/latest".format(parsed["pkg"]),
                headers=headers,
            ).json()
            parsed["tag"] = details["version"]
        except Exception:
            raise Exception("Could not get latest version for: {}".format(url))
    if parsed["tag"]:
        parsed["tagged_url"] = "https://www.npmjs.com/package/{}/v/{}{}".format(
            parsed["pkg"],
            parsed["tag"],
            "?private_token={}".format(private_token) if private_token else "",
        )
    return parsed


def parse_url(url: str, get_latest_if_none=False) -> dict[str, Optional[str]]:
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


def split_url_and_private_token(url: str) -> tuple[str, Optional[str]]:
    private_token = None
    if "?" in url:
        url, query = url.split("?")
        params = {k: v[0] for k, v in parse_qs(query).items()}
        private_token = params.get("private_token", None)
    return url.strip("/"), private_token


# passing `tag` overrides whatever is in the URL
def download_plugin_archive(url: str, tag: Optional[str] = None) -> bytes:
    parsed_url = parse_url(url)
    headers = {}

    if parsed_url["type"] == "github":
        if not (tag or parsed_url.get("tag", None)):
            raise Exception("No GitHub tag given!")
        url = "https://github.com/{user}/{repo}/archive/{tag}.zip".format(
            user=parsed_url["user"],
            repo=parsed_url["repo"],
            tag=tag or parsed_url["tag"],
        )
        token = parsed_url["private_token"] or settings.GITHUB_TOKEN
        if token:
            headers = {"Authorization": "token {}".format(token)}

    elif parsed_url["type"] == "gitlab":
        url_tag = tag or parsed_url.get("tag", None)
        url_project = parsed_url["project"]
        if not url_tag or not url_project:
            raise Exception("No GitLab tag or project given!")
        url = "https://gitlab.com/api/v4/projects/{project}/repository/archive.zip?sha={tag}".format(
            project=quote(url_project, safe=""), tag=url_tag
        )
        token = parsed_url["private_token"] or settings.GITLAB_TOKEN
        if token:
            headers = {"Authorization": "Bearer {}".format(token)}

    elif parsed_url["type"] == "npm":
        pkg = parsed_url["pkg"]
        if not pkg or (not tag and not parsed_url.get("tag", None)):
            raise Exception("No npm project or version given")
        url = "https://registry.npmjs.org/{pkg}/-/{repo}-{tag}.tgz".format(
            pkg=pkg, repo=pkg.split("/")[-1], tag=tag or parsed_url["tag"]
        )
        token = parsed_url["private_token"] or settings.NPM_TOKEN
        if token:
            headers = {"Authorization": "Bearer {}".format(token)}
    else:
        raise Exception("Unknown Repository Format")

    response = requests.get(url, headers=headers)
    if not response.ok:
        raise Exception("Could not download archive from {}".format(parsed_url["type"]))

    if parsed_url["type"] == "github" and parsed_url["path"]:
        return rezip_subdirectory(response.content, parsed_url["path"])

    return response.content


def load_json_file(filename: str):
    try:
        with open(filename, encoding="utf_8") as reader:
            return json.loads(reader.read())
    except FileNotFoundError:
        return None


def rezip_subdirectory(archive: bytes, path: str):
    zip_file = ZipFile(io.BytesIO(archive), "r")
    root_folder = zip_file.namelist()[0]
    zip_path = Path(zip_file) / root_folder / path
    zip_archive = io.BytesIO()

    with ZipFile(zip_archive, "w") as new_archive:
        new_archive.writestr(root_folder, root_folder)
        for file in zip_path.iterdir():
            new_archive.writestr(os.path.join(root_folder, file.name), file.read_bytes())

    return zip_archive.getvalue()


def get_file_from_zip_archive(archive: bytes, filename: str, *, json_parse: bool) -> Any:
    zip_file = ZipFile(io.BytesIO(archive), "r")
    root_folder = zip_file.namelist()[0]
    file_path = Path(zip_file)
    if file_path.joinpath(root_folder).is_dir():
        file_path = file_path / root_folder / filename
    else:
        file_path = file_path / filename
    with file_path.open() as reader:
        file_bytes = reader.read()
        if json_parse:
            return json.loads(file_bytes)
        if isinstance(file_bytes, bytes):
            return file_bytes.decode("utf-8")
        return str(file_bytes)


def get_file_from_tgz_archive(archive: bytes, filename, *, json_parse: bool) -> Any:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        if tar.getmembers()[0].isdir():
            root_folder = tar.getmembers()[0].name
        else:
            root_folder = "/".join(tar.getmembers()[0].name.split("/")[0:-1])
        file_path = os.path.join(root_folder, filename)
        extracted_file = tar.extractfile(file_path)
        if not extracted_file:
            return None
        file_bytes = extracted_file.read()
        return json.loads(file_bytes) if json_parse else file_bytes.decode("utf-8")


def get_file_from_archive(archive: bytes, filename: str, *, json_parse: bool = True) -> Any:
    try:
        try:
            return get_file_from_zip_archive(archive, filename, json_parse=json_parse)
        except (BadZipFile, FileNotFoundError):
            return get_file_from_tgz_archive(archive, filename, json_parse=json_parse)
    except (KeyError, ReadError):
        return None


def find_index_ts_in_archive(archive: bytes, main_filename: Optional[str] = None) -> str:
    main_filenames_to_try = [main_filename] if main_filename else ["index.js", "index.ts"]
    for main_filename in main_filenames_to_try:
        index_ts = get_file_from_archive(archive, main_filename, json_parse=False)
        if index_ts is not None:
            return index_ts
    raise ValueError(f"Could not find main file {' or '.join(main_filenames_to_try)}")


def extract_plugin_code(
    archive: bytes, plugin_json_parsed: Optional[dict[str, Any]] = None
) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Extract plugin.json, index.ts (which can be aliased) and frontend.tsx out of an archive.

    If plugin.json has already been parsed before this is called, its value can be passed in as an optimization."""
    if archive is None:
        raise ValueError(f"There is no archive to extract code from")
    # Extract plugin.json - required, might be provided already
    plugin_json: str
    if plugin_json_parsed is None:
        plugin_json_original = get_file_from_archive(archive, "plugin.json", json_parse=False)
        if not plugin_json_original:
            raise ValueError(f"Could not find plugin.json")
        try:
            plugin_json_parsed = json.loads(plugin_json_original)
        except json.JSONDecodeError as e:
            raise ValueError(f"Could not parse plugin.json: {e}") from e
    plugin_json = json.dumps(plugin_json_parsed)  # We serialize this even if just extracted from file, for minification
    assert plugin_json_parsed is not None  # Just to let mypy know this must be loaded at this point
    # Extract frontend.tsx - optional
    frontend_tsx: Optional[str] = get_file_from_archive(archive, "frontend.tsx", json_parse=False)
    # Extract site.ts - optional
    site_ts: Optional[str] = get_file_from_archive(archive, "site.ts", json_parse=False)
    # Extract index.ts - optional if frontend.tsx is present, otherwise required
    index_ts: Optional[str] = None
    try:
        index_ts = find_index_ts_in_archive(archive, plugin_json_parsed.get("main"))
    except ValueError:
        if frontend_tsx is None and site_ts is None:
            raise
    return plugin_json, index_ts, frontend_tsx, site_ts


def put_json_into_zip_archive(archive: bytes, json_data: dict, filename: str):
    input_zip = ZipFile(io.BytesIO(archive), "r")
    root_folder = input_zip.namelist()[0]
    file_path = os.path.join(root_folder, filename)

    zip_buffer = io.BytesIO()
    with ZipFile(zip_buffer, "a", ZIP_DEFLATED, False) as zip_file:
        for file in input_zip.filelist:
            if file.filename != file_path:
                zip_file.writestr(file, input_zip.read(file.filename))
        zip_file.writestr(file_path, json.dumps(json_data))
        for zfile in zip_file.filelist:
            zfile.create_system = 0

    return zip_buffer.getvalue()
