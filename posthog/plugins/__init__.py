import importlib
import os
import tempfile
import zipfile
from abc import ABC, abstractmethod

import pip
import requests

PLUGIN_PATH = os.path.join("posthog", "plugins")
URL_TEMPLATE = "{repo}/archive/{branch}.zip"
DEFAULT_BRANCHES = ["main", "master"]
PATH = os.path.abspath(os.getcwd())
ABS_PLUGIN_PATH = os.path.join(PATH, PLUGIN_PATH)

modules = []


def install(reqs):
    if hasattr(pip, "main"):
        pip.main(["install", "-r", reqs])
    else:
        pip._internal.main(["install", "-r", reqs])


def get_installed_plugins():
    plugins = [
        x for x in os.listdir(ABS_PLUGIN_PATH) if os.path.isdir(os.path.join(ABS_PLUGIN_PATH, x)) and x != "__pycache__"
    ]
    return plugins


def import_plugin(plugin):
    plugin_root = ".".join(os.path.split(PLUGIN_PATH))
    plugin_module_name = plugin_root + "." + plugin
    try:
        importlib.import_module(plugin_module_name)
    except Exception as e:
        return
    return plugin_module_name


def load_plugins(plugins):
    for repo in plugins:
        download_plugin(repo)

    plugins = get_installed_plugins()
    for plugin in plugins:
        req_file = os.path.join(ABS_PLUGIN_PATH, plugin, "requirements.txt")
        install(req_file)
        module = import_plugin(plugin)
        modules.append(module)


def download_plugin(repo):
    for branch in DEFAULT_BRANCHES:
        try:
            url = URL_TEMPLATE.format(repo=repo, branch=branch)
            r = requests.get(url)
            break
        except requests.RequestException:
            continue
    with tempfile.TemporaryFile() as f:
        f.write(r.content)
        with zipfile.ZipFile(f, "r") as zip_ref:
            plugin_path = os.path.join(PATH, PLUGIN_PATH)
            zip_ref.extractall(plugin_path)


class PluginBaseClass(ABC):
    @abstractmethod
    def process_event(self, event):
        pass

    @abstractmethod
    def process_person(self, event):
        pass

    @abstractmethod
    def process_identify(self, event):
        pass
