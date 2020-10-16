import datetime
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Dict, List, Optional, Type

from .cache import PluginCache


@dataclass
class PosthogEvent:
    ip: str
    site_url: str
    event: str
    distinct_id: str
    team_id: int
    properties: Dict[Any, Any]
    timestamp: datetime.datetime


# Contains metadata and the python module for a plugin
@dataclass
class PluginModule:
    id: int  # id in the Plugin model
    name: str  # name in the Plugin model
    url: str  # url in the Plugin model, can be https: or file:
    tag: str  # tag in the Plugin model
    module_name: str  # name of the module, "posthog.plugins.plugin_{id}_{name}_{tag}"
    plugin_path: str  # path of the local folder or the temporary .zip file for github
    requirements: List[str]  # requirements.txt split into lines
    module: ModuleType  # python module
    plugin: Type["PluginBaseClass"]  # plugin base class extracted from the exports in the module


# Contains per-team config for a plugin
@dataclass
class TeamPlugin:
    team: int  # team id
    plugin: int  # plugin id
    name: str  # plugin name
    tag: str  # plugin tag
    config: Dict[str, Any]  # config from the DB
    loaded_class: Optional["PluginBaseClass"]  # link to the class
    plugin_module: PluginModule  # link to the module


class PluginBaseClass:
    def __init__(self, config: TeamPlugin):
        self.config = config.config
        self.team = config.team
        self.cache = PluginCache(scope="{}/{}".format(config.name, config.team))
        self.team_init()

    @staticmethod
    def instance_init():
        pass

    def team_init(self):
        pass

    def schedule_jobs(self, sender):
        pass

    def process_event(self, event: PosthogEvent):
        pass

    def process_alias(self, event: PosthogEvent):
        pass

    def process_identify(self, event: PosthogEvent):
        pass
