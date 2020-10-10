import datetime
import inspect
import os
import pickle
import tempfile
import zipimport
from dataclasses import dataclass
from typing import Any, Dict, List

import fakeredis  # type: ignore
import pip
import redis
from django.conf import settings

from posthog.cache import get_redis_instance
from posthog.utils import SingletonDecorator

REDIS_INSTANCE = get_redis_instance()


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
    def __init__(self, config: any):
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


@dataclass
class PluginModule:
    id: int
    name: str
    tag: str
    module: any
    plugin: PluginBaseClass


@dataclass
class TeamPlugin:
    team: int
    plugin: int
    name: str
    tag: str
    config: Dict[str, any]
    loaded_class: PluginBaseClass
    plugin_module: PluginModule


class _Plugins:
    def __init__(self):
        self.plugins: List[any] = []  # type not loaded yet
        self.plugin_configs: List[any] = []  # type not loaded yet
        self.plugins_by_id: Dict[int, PluginModule] = {}
        self.plugins_by_team: Dict[int, List[TeamPlugin]] = {}

        self.load_plugins()
        self.load_plugin_configs()
        self.start_reload_pubsub()

    def load_plugins(self):
        from posthog.models.plugin import Plugin

        self.plugins = Plugin.objects.all()

        for plugin in self.plugins:
            old_plugin = self.plugins_by_id.get(plugin.id, None)

            # skip loading if same tag already loaded
            if old_plugin:
                if old_plugin.tag == plugin.tag:
                    continue
                self.unregister_plugin(plugin.id)

            # TODO: symlink if local plugin?
            new_file, filename = tempfile.mkstemp(prefix=plugin.name, suffix=".zip")
            os.write(new_file, plugin.archive)
            os.close(new_file)

            importer = zipimport.zipimporter(filename)

            try:
                requirements = importer.get_data("{}-{}/requirements.txt".format(plugin.name, plugin.tag))
                requirements = requirements.decode("utf-8").split("\n")
                for requirement in requirements:
                    if requirement:
                        self.install_requirement(requirement)
            except IOError:
                pass

            module = importer.load_module("{}-{}".format(plugin.name, plugin.tag))

            for item in module.__dict__.items():
                if inspect.isclass(item[1]) and item[0] != "PluginBaseClass" and issubclass(item[1], PluginBaseClass):
                    self.plugins_by_id[plugin.id] = PluginModule(
                        id=plugin.id, name=plugin.name, tag=plugin.tag, module=module, plugin=item[1]
                    )

    def unregister_plugin(self, id):
        if not self.plugins_by_id.get(id, None):
            return

        # TODO: any way to properly remove the old one from memory?
        # TODO: check also plugins_by_team and delete them from there...
        del self.plugins_by_id[id].plugin
        del self.plugins_by_id[id].module
        del self.plugins_by_id[id]

    def load_plugin_configs(self):
        from posthog.models.plugin import PluginConfig

        self.plugin_configs = PluginConfig.objects.filter(enabled=True).order_by("team", "order").all()
        self.plugins_by_team: Dict[int, List[TeamPlugin]] = {}

        for plugin_config in self.plugin_configs:
            team_plugins = self.plugins_by_team.get(plugin_config.team_id, None)
            if not team_plugins:
                team_plugins = []
                self.plugins_by_team[plugin_config.team_id] = team_plugins

            plugin_module = self.plugins_by_id[plugin_config.plugin_id]

            if plugin_module:
                try:
                    team_plugin = TeamPlugin(
                        team=plugin_config.team_id,
                        plugin=plugin_config.plugin_id,
                        name=plugin_module.name,
                        tag=plugin_module.tag,
                        config=plugin_config.config,
                        plugin_module=plugin_module,
                        loaded_class=None,
                    )
                    loaded_class = plugin_module.plugin(team_plugin)
                    team_plugin.loaded_class = loaded_class
                    team_plugins.append(team_plugin)
                except Exception as e:
                    print('🔻🔻🔻 Error loading plugin "{}" for team {}'.format(plugin_module.name, plugin_config.team_id))
                    print(e)

    @staticmethod
    def install_requirement(requirement):
        if hasattr(pip, "main"):
            pip.main(["install", requirement])
        else:
            pip._internal.main(["install", requirement])

    def exec_plugins(self, event, team_id):
        team_plugins = self.plugins_by_team.get(team_id, None)

        if team_plugins:
            for plugin in team_plugins:
                print("!!! Running plugin {}, with config {}".format(plugin.name, plugin.config))

                event = self.exec_plugin(plugin.loaded_class, event, "process_event")
                if event.event == "$identify":
                    event = self.exec_plugin(plugin.loaded_class, event, "process_identify")
                if event.event == "$create_alias":
                    event = self.exec_plugin(plugin.loaded_class, event, "process_alias")

        return event

    def exec_plugin(self, module, event, method="process_event"):
        f = getattr(module, method)
        event = f(event)
        return event

    def reload_plugins(self, message):
        self.load_plugins()
        self.load_plugin_configs()

    def start_reload_pubsub(self):
        pubsub = REDIS_INSTANCE.pubsub()
        pubsub.subscribe(**{"plugin-reload-channel": self.reload_plugins})
        pubsub.run_in_thread(sleep_time=1, daemon=True)

    @staticmethod
    def publish_reload_command():
        REDIS_INSTANCE.publish("plugin-reload-channel", "yeah!")


Plugins = SingletonDecorator(_Plugins)
