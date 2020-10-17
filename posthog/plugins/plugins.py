import importlib
import importlib.util
import inspect
import os
import tempfile
import zipimport
from typing import Dict, List, Optional, Union
from zipfile import ZipFile

from django.db.models import F

from posthog.cache import get_redis_instance
from posthog.models.plugin import Plugin, PluginConfig
from posthog.utils import SingletonDecorator

from .models import PluginBaseClass, PluginError, PluginModule, PosthogEvent, TeamPlugin
from .sync import sync_global_plugin_config, sync_posthog_json_plugins

REDIS_INSTANCE = get_redis_instance()


class _Plugins:
    def __init__(self):
        self.redis = get_redis_instance()
        self.plugins: List[Plugin] = []  # type not loaded yet
        self.plugin_configs: List[PluginConfig] = []  # type not loaded yet
        self.plugins_by_id: Dict[int, PluginModule] = {}
        self.plugins_by_team: Dict[Union[int, None], List[TeamPlugin]] = {}

        sync_posthog_json_plugins()
        sync_global_plugin_config()

        self.load_plugins()
        self.load_plugin_configs()
        self.start_reload_pubsub()

    def load_plugins(self):
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
                self.register_error(plugin, PluginError('Archive not downloaded and it\'s not a local "file:" plugin'))
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
                    try:
                        module = importlib.util.module_from_spec(spec)
                        if module:
                            spec.loader.exec_module(module)  # type: ignore
                        else:
                            self.register_error(plugin, PluginError("Could not find module in __init__.py"))
                            continue
                    except Exception as e:
                        self.register_error(plugin, PluginError("Error initializing __init__.py"), e)
                        continue
                else:
                    self.register_error(plugin, PluginError("Could not find module in __init__.py"))
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
                except PluginError as e:
                    self.register_error(plugin, e)
                    continue

                try:
                    importer = zipimport.zipimporter(plugin_path)
                    module = importer.load_module(module_name)
                except zipimport.ZipImportError as e:
                    self.register_error(
                        plugin, PluginError("Could not find __init__.py from the plugin zip archive"), e
                    )
                    os.unlink(plugin_path)  # temporary file no longer needed
                    continue
                except Exception as e:
                    self.register_error(plugin, PluginError("Error initializing __init__.py"), e)
                    continue

                os.unlink(plugin_path)  # temporary file no longer needed

            found_plugin = False
            for item in module.__dict__.items():
                if inspect.isclass(item[1]) and item[0] != "PluginBaseClass" and issubclass(item[1], PluginBaseClass):
                    found_plugin = True
                    try:
                        item[1].instance_init()
                    except Exception as e:
                        self.register_error(
                            plugin, PluginError('Error running instance_init() on plugin "{}"'.format(plugin.name)), e
                        )
                        continue

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

            if found_plugin:
                if local_plugin:
                    print('🔗 Loaded plugin "{}" from "{}"'.format(plugin.name, plugin_path))
                else:
                    print(
                        '🔗 Loaded plugin "{}" from "{}" (cached, tag "{}")'.format(plugin.name, plugin.url, plugin.tag)
                    )
            else:
                self.register_error(plugin, PluginError("Could not find any exported class of type PluginBaseClass"))
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
        self.plugin_configs = list(
            PluginConfig.objects.filter(enabled=True).order_by(F("team_id").desc(nulls_first=True), "order").all()
        )
        self.plugins_by_team = {}

        for plugin_config in self.plugin_configs:
            team_plugins = self.plugins_by_team.get(plugin_config.team_id, None)
            if not team_plugins:
                team_plugins = []
                self.plugins_by_team[plugin_config.team_id] = team_plugins

            plugin_module = self.plugins_by_id.get(plugin_config.plugin_id, None)

            if plugin_module:
                team_plugin = TeamPlugin(
                    team=plugin_config.team_id,
                    plugin=plugin_config.plugin_id,
                    order=plugin_config.order,
                    name=plugin_module.name,
                    tag=plugin_module.tag,
                    config=plugin_config.config,
                    plugin_module=plugin_module,
                    loaded_class=None,
                )
                try:
                    loaded_class = plugin_module.plugin(team_plugin)
                    team_plugin.loaded_class = loaded_class
                    team_plugins.append(team_plugin)
                except Exception as e:
                    self.register_team_error(
                        team_plugin, PluginError("Error loading plugin"), e,
                    )

        # if we have global plugins, add them to the team plugins list for all teams that have team plugins
        global_plugins = self.plugins_by_team.get(None, None)
        if global_plugins and len(global_plugins) > 0:
            global_plugin_keys = {}
            for plugin in global_plugins:
                global_plugin_keys[plugin.name] = True
            for team, team_plugins in self.plugins_by_team.items():
                new_team_plugins = global_plugins.copy()
                for plugin in team_plugins:
                    if not global_plugin_keys.get(plugin.name, None):
                        new_team_plugins.append(plugin)
                new_team_plugins.sort(key=order_by_order)
                self.plugins_by_team[team] = new_team_plugins

    def install_requirements(self, plugin_name: str, requirements: List[str]):
        if len(requirements) > 0:
            print('Loading requirements for plugin "{}": {}'.format(plugin_name, requirements))

        # TODO: Provide some way to work over version conflicts, e.g. if one plugin requires
        #       requests==2.22.0 and another requires requests==2.22.1. At least emit warnings!
        for requirement in requirements:
            if requirement:
                self.install_requirement(requirement)

    def install_requirement(self, requirement: str):
        import pip  # type: ignore

        if hasattr(pip, "main"):
            resp = pip.main(["install", requirement])
        else:
            resp = pip._internal.main(["install", requirement])

        if resp != 0:
            raise PluginError("Error installing requirement: {}".format(requirement))

    def exec_plugins(self, event: PosthogEvent, team_id: int):
        team_plugins = self.plugins_by_team.get(team_id, None)
        global_plugins = self.plugins_by_team.get(None, [])
        plugins_to_run = team_plugins if team_plugins else global_plugins

        for team_plugin in plugins_to_run:
            if event:
                event = self.exec_plugin(team_plugin, event, "process_event")
            if event and event.event == "$identify":
                event = self.exec_plugin(team_plugin, event, "process_identify")
            if event and event.event == "$create_alias":
                event = self.exec_plugin(team_plugin, event, "process_alias")

        return event

    def exec_plugin(self, team_plugin: TeamPlugin, event: PosthogEvent, method="process_event"):
        try:
            f = getattr(team_plugin.loaded_class, method)
            event = f(event)
        except Exception as e:
            self.register_team_error(
                team_plugin, PluginError("Error running method '{}'".format(method)), e,
            )
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

    @staticmethod
    def register_error(plugin: Union[Plugin, int], plugin_error: PluginError, error: Optional[Exception] = None):
        if isinstance(plugin, int):
            plugin = Plugin.objects.get(pk=plugin)

        print('🔻🔻 Plugin name="{}", url="{}", tag="{}"'.format(plugin.name, plugin.url, plugin.tag))
        print("🔻🔻 Error: {}".format(plugin_error.message))

        plugin.error = {"message": plugin_error.message}
        if error:
            plugin.error["exception"] = str(error)
            print("🔻🔻 Exception: {}".format(str(error)))
        plugin.save()

    @staticmethod
    def register_team_error(team_plugin: TeamPlugin, plugin_error: PluginError, error: Optional[Exception] = None):
        print('🔻🔻 Plugin name="{}", team="{}", tag="{}"'.format(team_plugin.name, team_plugin.team, team_plugin.tag))
        print("🔻🔻 Error: {}".format(plugin_error.message))

        plugin_config = PluginConfig.objects.get(team=team_plugin.team, plugin=team_plugin.plugin)
        if plugin_config:
            plugin_config.error = {"message": plugin_error.message}
            if error:
                plugin_config.error["exception"] = str(error)
                print("🔻🔻 Exception: {}".format(str(error)))
            plugin_config.save()


Plugins = SingletonDecorator(_Plugins)


def order_by_order(e):
    return e.order
