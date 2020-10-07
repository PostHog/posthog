import datetime
import importlib
import os
import tempfile
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict

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
        if repo.startswith("http:") or repo.startswith("https:"):
            download_plugin(repo)
        else:
            symlink_plugin(repo)

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


def symlink_plugin(path):
    real_path = os.path.realpath(path)
    path_parts = os.path.split(real_path)
    plugin_path = os.path.join(PATH, PLUGIN_PATH, path_parts[-1])
    if os.path.exists(plugin_path) or os.path.islink(plugin_path):
        os.unlink(plugin_path)
    os.symlink(real_path, plugin_path)


def get_plugin_modules():
    return PluginBaseClass.__subclasses__()


def exec_plugins(event):
    mods = get_plugin_modules()
    for mod in mods:
        event = exec_plugin(mod, event, "process_event")
        if event.event == "$identify":
            event = exec_plugin(mod, event, "process_identify")
        if event.event == "$create_alias":
            event = exec_plugin(mod, event, "process_alias")


def exec_plugin(module, event, method="process_event"):
    f = getattr(module, method)
    event = f(event)
    return event


def schedule_tasks():
    mods = get_plugin_modules()
    for mod in mods:
        f = getattr(mod, "schedule_jobs")
        f()


@dataclass
class PosthogEvent:
    ip: str
    site_url: str
    event: str
    distinct_id: str
    team_id: int
    properties: Dict[Any, Any]
    timestamp: datetime.datetime


class PluginBaseClass(ABC):
    @abstractmethod
    def schedule_jobs(self, sender):
        pass

    @abstractmethod
    def process_event(self, event: PosthogEvent):
        pass

    @abstractmethod
    def process_alias(self, event: PosthogEvent):
        pass

    @abstractmethod
    def process_identify(self, event: PosthogEvent):
        pass
