import datetime
import importlib
import json
import os
import pickle
import re
import shutil
import tempfile
import traceback
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List

import fakeredis  # type: ignore
import pip
import redis
import requests
from django.conf import settings

PLUGIN_PATH = os.path.join("posthog", "plugins")
URL_TEMPLATE = "{repo}/archive/{branch}.zip"
DEFAULT_BRANCHES = ["main", "master"]
PATH = os.path.abspath(os.getcwd())
ABS_PLUGIN_PATH = os.path.join(PATH, PLUGIN_PATH)


def cleanse_plugin_directory():
    for x in os.listdir(ABS_PLUGIN_PATH):
        if os.path.islink(dir):
            os.unlink(dir)
        elif os.path.isdir(os.path.join(ABS_PLUGIN_PATH, x)) and x != "__pycache__":
            dir = os.path.join(ABS_PLUGIN_PATH, x)
            shutil.rmtree(dir)


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
        print('🔻 Can not import plugin "{}"'.format(plugin))
        trace_back = traceback.format_exc()
        message = str(e) + " " + str(trace_back)
        print(message)
        return None
    return plugin_module_name


def load_plugins():
    cleanse_plugin_directory()
    plugins = get_plugin_config().order
    for repo in plugins:
        if not repo.path:
            download_plugin(repo.url)
        else:
            symlink_plugin(repo.path)
    plugins = get_installed_plugins()
    for plugin in plugins:
        req_file = os.path.join(ABS_PLUGIN_PATH, plugin, "requirements.txt")
        install(req_file)
        import_plugin(plugin)


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
    return event


def get_plugin_config():
    with open("posthog.json", "r") as f:
        conf = json.loads(f.read()).get("plugins", None)
    plugin_configs = PluginConfigs(order=[], dict={})
    for plugin in conf:
        ppc = PluginConfig(
            path=plugin.get("path", None), url=plugin.get("url", None), config=plugin.get("config", None)
        )
        plugin_configs.dict[ppc.name] = ppc
        plugin_configs.order.append(ppc)
    return plugin_configs


def get_module_config(module):
    module_name = module.__module__.split(".")[-1]
    module_name = re.sub("-main$", "", module_name)
    module_name = re.sub("-master$", "", module_name)
    plugin_config = get_plugin_config()
    module_config = plugin_config.dict[module_name].config
    return module_config


def exec_plugin(Module, event, method="process_event"):
    mc = get_module_config(Module)
    module = Module(mc)
    f = getattr(module, method)
    event = f(event)
    return event


def schedule_tasks():
    mods = get_plugin_modules()
    for Mod in mods:
        mc = get_module_config(Mod)
        mod = Mod(mc)
        f = getattr(mod, "schedule_jobs")
        f()


@dataclass
class PluginConfig:
    url: str
    path: str
    config: Dict[Any, Any]

    @property
    def name(self):
        if self.path:
            return os.path.split(os.path.realpath(self.path))[-1]
        return self.url.split("/")[-1]


@dataclass
class PluginConfigs:
    order: List[PluginConfig]
    dict: Dict[str, PluginConfig]


@dataclass
class PosthogEvent:
    ip: str
    site_url: str
    event: str
    distinct_id: str
    team_id: int
    properties: Dict[Any, Any]
    timestamp: datetime.datetime


class PluginCache:
    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        if settings.TEST:
            self.redis = fakeredis.FakeStrictRedis()
        elif settings.REDIS_URL:
            self.redis = redis.from_url(settings.REDIS_URL, db=0)

    def format_key(self, key):
        key = "{plugin_name}_{key}".format(plugin_name=self.plugin_name, key=key)
        return key

    def set(self, key: str, value: Any):
        key = self.format_key(key)
        value = pickle.dumps(value)
        self.redis.set(key, value)

    def get(self, key) -> Any:
        key = self.format_key(key)
        str_value = self.redis.get(key)
        value = pickle.loads(str_value)
        return value


class PluginBaseClass:
    def __init__(self, config: PluginConfig):
        self.config = config.config
        self.cache = PluginCache(plugin_name=config.name)

    def schedule_jobs(self, sender):
        pass

    def process_event(self, event: PosthogEvent):
        pass

    def process_alias(self, event: PosthogEvent):
        pass

    def process_identify(self, event: PosthogEvent):
        pass
