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
from typing import Any, Dict, List, Optional

import fakeredis  # type: ignore
import pip
import redis
import requests
from django.conf import settings

from posthog.models.plugin import Plugin
from posthog.models.team import Team
from posthog.utils import SingletonDecorator

PLUGIN_PATH = os.path.join("posthog", "plugins")
URL_TEMPLATE = "{repo}/archive/{branch}.zip"
DEFAULT_BRANCHES = ["main", "master"]
PATH = os.path.abspath(os.getcwd())
ABS_PLUGIN_PATH = os.path.join(PATH, PLUGIN_PATH)


@dataclass
class PluginConfig:
    url: Optional[str]
    path: Optional[str]
    config: Dict[Any, Any]
    config_schema: Optional[Dict[Any, Any]]
    enabled: bool = True
    order: int = 100
    display_name: str = ""
    team: int = 0
    description: str = ""

    @property
    def name(self):
        if self.path:
            return os.path.split(os.path.realpath(self.path))[-1]
        return self.url.split("/")[-1]


@dataclass
class PluginConfigs:
    ordered: List[PluginConfig]
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
        if not str_value:
            return None
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


class _Plugins:
    def __init__(self):
        self.load_plugins()
        self.plugin_configs = self.get_plugin_config()
        self.cleanse_plugin_directory()
        self.plugins = self.plugin_configs.ordered

    def load_plugins(self):
        self.cleanse_plugin_directory()
        self.plugins = self.get_plugin_config().ordered
        for repo in self.plugins:
            if not repo.path:
                self.download_plugin(repo.url)
            else:
                self.symlink_plugin(repo.path)
        plugins = self.get_installed_plugins()
        for plugin in plugins:
            req_file = os.path.join(ABS_PLUGIN_PATH, plugin, "requirements.txt")
            self.install(req_file)
            self.import_plugin(plugin)

    @staticmethod
    def cleanse_plugin_directory():
        for x in os.listdir(ABS_PLUGIN_PATH):
            pdir = os.path.join(ABS_PLUGIN_PATH, x)
            if os.path.islink(pdir):
                os.unlink(pdir)
            elif os.path.isdir(pdir) and x != "__pycache__":
                shutil.rmtree(pdir)

    @staticmethod
    def install(reqs):
        if hasattr(pip, "main"):
            pip.main(["install", "-r", reqs])
        else:
            pip._internal.main(["install", "-r", reqs])

    @staticmethod
    def get_installed_plugins():
        plugins = [
            x
            for x in os.listdir(ABS_PLUGIN_PATH)
            if os.path.isdir(os.path.join(ABS_PLUGIN_PATH, x)) and x != "__pycache__"
        ]
        return plugins

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def symlink_plugin(path):
        real_path = os.path.realpath(path)
        path_parts = os.path.split(real_path)
        plugin_path = os.path.join(PATH, PLUGIN_PATH, path_parts[-1])
        if os.path.exists(plugin_path) or os.path.islink(plugin_path):
            os.unlink(plugin_path)
        os.symlink(real_path, plugin_path)

    @staticmethod
    def get_plugin_modules():
        return PluginBaseClass.__subclasses__()

    def exec_plugins(self, event):
        mods = self.get_plugin_modules()
        for mod in mods:
            event = self.exec_plugin(mod, event, "process_event")
            if event.event == "$identify":
                event = self.exec_plugin(mod, event, "process_identify")
            if event.event == "$create_alias":
                event = self.exec_plugin(mod, event, "process_alias")
        return event

    def update_plugin_config(self):
        self.plugin_configs = self.get_plugin_config()

    @staticmethod
    def get_plugin_config(team: Team = None) -> PluginConfigs:
        # load plugins from json config
        with open("posthog.json", "r") as f:
            json_conf = json.loads(f.read()).get("plugins", None)
        plugin_configs = PluginConfigs(ordered=[], dict={})
        for plugin in json_conf:
            path = plugin.get("path", None)
            url = plugin.get("url", None)
            name = plugin.get("name", None)
            config = plugin.get("config", None)
            order = plugin.get("order", 1000)
            team = plugin.get("team", None)
            enabled = plugin.get("enabled", True)
            if not name:
                if path:
                    name = os.path.split(os.path.realpath(plugin["path"]))[-1]
                else:
                    name = url.split("/")[-1]
            ppc = PluginConfig(
                path=path,
                url=url,
                config=config,
                config_schema=None,
                display_name=name,
                order=order,
                team=team,
                enabled=enabled,
            )
            plugin_configs.dict[ppc.name] = ppc
            plugin_configs.ordered.append(ppc)

        # Load plugins from model
        if team:
            plugins = Plugin.objects.filter(team=Team)
        else:
            plugins = Plugin.objects.all()
        for plugin in plugins:
            ppc = PluginConfig(
                path=None,
                url=plugin.url,
                config=plugin.config,
                config_schema=plugin.configSchema,
                display_name=plugin.name,
                order=plugin.order,
                team=plugin.team,
                enabled=plugin.enabled,
            )
            plugin_configs.dict[ppc.name] = ppc
            plugin_configs.ordered.append(ppc)
        plugin_configs.ordered.sort(key=lambda x: x.order)
        return plugin_configs

    def get_module_config(self, module):
        module_name = module.__module__.split(".")[-1]
        module_name = re.sub("-main$", "", module_name)
        module_name = re.sub("-master$", "", module_name)
        module_config = self.plugin_configs.dict[module_name]
        return module_config

    def exec_plugin(self, Module, event, method="process_event"):
        mc = self.get_module_config(Module)
        module = Module(mc)
        f = getattr(module, method)
        event = f(event)
        return event

    def schedule_tasks(self):
        mods = self.get_plugin_modules()
        for Mod in mods:
            mc = self.get_module_config(Mod)
            mod = Mod(mc)
            f = getattr(mod, "schedule_jobs")
            f()


Plugins = SingletonDecorator(_Plugins)
