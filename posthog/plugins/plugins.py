import importlib
import importlib.util
import inspect
import os
import tempfile
import zipimport
from typing import Dict, List, Optional
from zipfile import ZipFile

from posthog.cache import get_redis_instance
from posthog.utils import SingletonDecorator

from .models import PluginBaseClass, PluginModule, TeamPlugin

REDIS_INSTANCE = get_redis_instance()


class _Plugins:
    def __init__(self):
        from posthog.models.plugin import Plugin, PluginConfig

        from .sync import sync_global_plugin_config, sync_posthog_json_plugins

        self.redis = get_redis_instance()
        self.plugins: List[Plugin] = []  # type not loaded yet
        self.plugin_configs: List[PluginConfig] = []  # type not loaded yet
        self.plugins_by_id: Dict[int, PluginModule] = {}
        self.plugins_by_team: Dict[int, List[TeamPlugin]] = {}

        sync_posthog_json_plugins()
        sync_global_plugin_config()

        self.load_plugins()
        self.load_plugin_configs()
        self.start_reload_pubsub()

    def load_plugins(self):
        from posthog.models.plugin import Plugin

        self.plugins = list(Plugin.objects.all())

        # unregister plugins no longer in use
        active_plugin_ids = {}
        for plugin in self.plugins:
            active_plugin_ids[plugin.id] = True
        plugin_ids = list(self.plugins_by_id.keys())
        for plugin_id in plugin_ids:
            if not active_plugin_ids.get(plugin_id, None):
                self.unregister_plugin(plugin_id)

        # register plugins not yet seen
        for plugin in self.plugins:
            local_plugin = plugin.url.startswith("file:") and not plugin.archive
            old_plugin = self.plugins_by_id.get(plugin.id, None)
            requirements = []

            if old_plugin:
                # skip reloading if same tag already loaded
                if old_plugin.url == plugin.url and old_plugin.tag == plugin.tag and not local_plugin:
                    continue
                self.unregister_plugin(plugin.id)

            if not plugin.archive and not local_plugin:
                print(
                    '🔻 Plugin "{}" archive not downloaded and it\'s not a local "file:" path ({})'.format(
                        plugin.name, plugin.url
                    )
                )
                continue

            if local_plugin:
                module_name = "posthog.plugins.plugin_{id}_{name}".format(id=plugin.id, name=plugin.name)
                plugin_path = os.path.realpath(plugin.url.replace("file:", "", 1))

                try:
                    requirements_path = os.path.join(plugin_path, "requirements.txt")
                    requirements_file = open(requirements_path, "r")
                    requirements = requirements_file.read().split("\n")
                    requirements = [x for x in requirements if x]
                    requirements_file.close()
                    self.install_requirements(plugin.name, requirements)
                except FileNotFoundError:
                    pass

                spec = importlib.util.spec_from_file_location(module_name, os.path.join(plugin_path, "__init__.py"))
                if spec:
                    module = importlib.util.module_from_spec(spec)
                    if module:
                        spec.loader.exec_module(module)  # type: ignore
                    else:
                        print(
                            '🔻🔻🔻 Could not find module in __init__.py for plugin "{}" in: {}'.format(
                                plugin.name, plugin_path
                            )
                        )
                        continue
                else:
                    print(
                        '🔻🔻🔻 Could not find module in __init__.py for plugin "{}" in: {}'.format(
                            plugin.name, plugin_path
                        )
                    )
                    continue

            else:
                module_name = "{}-{}".format(plugin.name, plugin.tag)
                fd, plugin_path = tempfile.mkstemp(prefix=plugin.name + "-", suffix=".zip")
                os.write(fd, plugin.archive)
                os.close(fd)

                zip_file = ZipFile(plugin_path)
                zip_root_folder = zip_file.namelist()[0]

                try:
                    requirements_path = os.path.join(zip_root_folder, "requirements.txt")
                    with zip_file.open(requirements_path) as requirements_zip_file:
                        requirements = requirements_zip_file.read().decode("utf-8").split("\n")
                        requirements = [x for x in requirements if x]
                    self.install_requirements(plugin.name, requirements)
                except KeyError:
                    pass  # no requirements.txt found

                try:
                    importer = zipimport.zipimporter(plugin_path)
                    module = importer.load_module(module_name)
                except zipimport.ZipImportError as e:
                    print(
                        '🔻🔻 Could not load zip plugin: name="{}", url="{}", tag="{}"'.format(
                            plugin.name, plugin.url, plugin.tag
                        )
                    )
                    print("🔻🔻 Exception: {}".format(e.msg))  # type: ignore
                    os.unlink(plugin_path)  # temporary file no longer needed
                    return

                os.unlink(plugin_path)  # temporary file no longer needed

            found_plugin = False
            for item in module.__dict__.items():
                if inspect.isclass(item[1]) and item[0] != "PluginBaseClass" and issubclass(item[1], PluginBaseClass):
                    found_plugin = True
                    self.plugins_by_id[plugin.id] = PluginModule(
                        id=plugin.id,
                        name=plugin.name,
                        tag=plugin.tag,
                        url=plugin.url,
                        module_name=module_name,
                        plugin_path=plugin_path,
                        requirements=requirements,
                        plugin=item[1],
                        module=module,
                    )
                    item[1].instance_init()

            if found_plugin:
                if local_plugin:
                    print('🔗 Loaded plugin "{}" from "{}"'.format(plugin.name, plugin_path))
                else:
                    print(
                        '🔗 Loaded plugin "{}" from "{}" (cached, tag "{}")'.format(plugin.name, plugin.url, plugin.tag)
                    )
            else:
                print(
                    '🔻🔻 For plugin "{}" could not find any exported class of type PluginBaseClass'.format(plugin.name)
                )
                print('🔻🔻 Plugin: url="{}", tag="{}"'.format(plugin.url, plugin.tag))
                continue

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

        self.plugin_configs = list(PluginConfig.objects.filter(enabled=True).order_by("team", "order").all())
        self.plugins_by_team = {}

        for plugin_config in self.plugin_configs:
            team_plugins = self.plugins_by_team.get(plugin_config.team_id, None)
            if not team_plugins:
                team_plugins = []
                self.plugins_by_team[plugin_config.team_id] = team_plugins

            plugin_module = self.plugins_by_id.get(plugin_config.plugin_id, None)

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

    def install_requirements(self, plugin_name, requirements):
        if len(requirements) > 0:
            print('Loading requirements for plugin "{}": {}'.format(plugin_name, requirements))

        # TODO: Provide some way to work over version conflicts, e.g. if one plugin requires
        #       requests==2.22.0 and another requires requests==2.22.1. At least emit warnings!
        for requirement in requirements:
            if requirement:
                self.install_requirement(requirement)

    def install_requirement(self, requirement):
        import pip  # type: ignore

        if hasattr(pip, "main"):
            pip.main(["install", requirement])
        else:
            pip._internal.main(["install", requirement])

    def exec_plugins(self, event, team_id):
        team_plugins = self.plugins_by_team.get(team_id, None)

        if team_plugins:
            for plugin in team_plugins:
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

    # using argument message just to be compatible with the pubsub interface
    def reload_plugins(self, message=None):
        self.load_plugins()
        self.load_plugin_configs()

    def start_reload_pubsub(self):
        if self.redis:
            pubsub = self.redis.pubsub()
            pubsub.subscribe(**{"plugin-reload-channel": self.reload_plugins})
            pubsub.run_in_thread(sleep_time=1, daemon=True)  # type: ignore
        else:
            print("🔻🔻🔻 Can not listen to plugin reload commands! No redis instance found!")

    def publish_reload_command(self, team_id: Optional[int] = None):
        if self.redis:
            self.redis.publish("plugin-reload-channel", str(team_id) if team_id else "__ALL__")
        else:
            print("🔻🔻🔻 Error reloading plugins! No redis instance found!")


Plugins = SingletonDecorator(_Plugins)
