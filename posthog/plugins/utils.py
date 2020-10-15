import re

import requests


def download_plugin_github_zip(repo: str, tag: str):
    url_template = "{repo}/archive/{tag}.zip"
    url = url_template.format(repo=re.sub("/$", "", repo), tag=tag)
    response = requests.get(url)
    if not response.ok:
        raise Exception("Could not download archive from GitHub")
    return response.content
