import json
import os
from typing import Any, Dict, List, Optional, Type

from .reload import reload_plugins_on_workers
from .utils import download_plugin_github_zip, load_json_file, load_json_zip_bytes


# def sync_plugin_config()
# - Runs on boot
# - Syncs information about plugins from posthog.json into the plugin model, downloading plugins as needed.
# - Will only download the same plugin/tag once.
# - Syncs globally enabled plugin config from posthog.json into the pluginconfig model.
def sync_plugin_config():
    changes = [sync_posthog_json_plugins(), sync_global_plugin_config()]
    if any(changes):
        reload_plugins_on_workers()


def sync_posthog_json_plugins(raise_errors=False, filename="posthog.json"):
    from posthog.models.plugin import Plugin

    json_plugins = get_json_plugins(raise_errors=raise_errors, filename=filename)
    did_something = False

    config_plugins: Dict[str, Dict[str, Any]] = {}

    for plugin in json_plugins:
        if plugin and plugin.get("name", None):
            config_plugins[plugin["name"]] = plugin

    db_plugins = {}
    for plugin in list(Plugin.objects.all()):
        # was added from the CLI, but no longer requested
        if plugin.from_json and not config_plugins.get(plugin.name, None):
            if plugin.from_web:
                plugin.from_json = False
                plugin.save()
                did_something = True
            else:
                plugin.delete()
                did_something = True
                continue
        db_plugins[plugin.name] = plugin

    for name, config_plugin in config_plugins.items():
        db_plugin = db_plugins.get(name, None)
        if not db_plugin:
            create_plugin_from_config(config_plugin)
            did_something = True
        elif not config_and_db_plugin_in_sync(config_plugin, db_plugin):
            update_plugin_from_config(db_plugin, config_plugin)
            did_something = True

    return did_something


def get_json_plugins(raise_errors=False, filename="posthog.json"):
    try:
        with open(filename, "r") as f:
            return json.loads(f.read()).get("plugins", [])
    except json.JSONDecodeError as e:
        print_or_raise(
            'JSONDecodeError when reading "posthog.json". Skipping json plugin sync! Please investigate!', raise_errors
        )
        return []
    except FileNotFoundError:
        return []


def create_plugin_from_config(config_plugin=None, raise_errors=False):
    from posthog.models.plugin import Plugin

    description = config_plugin.get("description", "")
    config_schema = {}

    if config_plugin.get("url", None):
        if not config_plugin.get("tag", None):
            print_or_raise(
                'No "tag" set for plugin "{}" enabled via posthog.json. Can\'t install!'.format(config_plugin["name"]),
                raise_errors,
            )
            return
        url = config_plugin["url"]
        tag = config_plugin["tag"]
        archive = download_plugin_github_zip(url, tag)
        json = load_json_zip_bytes(archive, "plugin.json")
        if json:
            description = json["description"]
            config_schema = json["config"]
    elif config_plugin.get("path", None):
        url = "file:{}".format(config_plugin["path"])
        tag = ""
        archive = None
        json = load_json_file(os.path.join(config_plugin["path"], "plugin.json"))
        if json:
            description = json["description"]
            config_schema = json["config"]
    else:
        print_or_raise(
            'No "url" or "path" set for plugin "{}" in posthog.json. Can\'t install!'.format(config_plugin["name"]),
            raise_errors,
        )
        return

    Plugin.objects.create(
        name=config_plugin["name"],
        description=description,
        url=url,
        tag=tag,
        archive=archive,
        config_schema=config_schema,
        from_json=True,
    )


def config_and_db_plugin_in_sync(config_plugin, db_plugin):
    url = config_plugin.get("url", "file:{}".format(config_plugin.get("path", "")))

    return (
        not url.startswith("file:")
        and db_plugin.from_json
        and db_plugin.url == url
        and db_plugin.tag == config_plugin.get("tag", "")
    )


def update_plugin_from_config(db_plugin, config_plugin):
    db_plugin.from_json = True
    new_url = config_plugin.get("url", "file:{}".format(config_plugin.get("path", "")))
    new_tag = config_plugin.get("tag", "")

    if db_plugin.url.startswith("file:") or new_url != db_plugin.url or new_tag != db_plugin.tag:
        db_plugin.url = new_url
        db_plugin.tag = new_tag
        if db_plugin.url.startswith("file:"):
            db_plugin.archive = None
            json = load_json_file(os.path.join(db_plugin.url.replace("file:", "", 1), "plugin.json"))
            if json:
                db_plugin.description = json["description"]
                db_plugin.config_schema = json["config"]
        else:
            db_plugin.archive = download_plugin_github_zip(db_plugin.url, db_plugin.tag)
            json = load_json_zip_bytes(db_plugin.archive, "plugin.json")
            if json:
                db_plugin.description = json["description"]
                db_plugin.config_schema = json["config"]

    db_plugin.save()


def print_or_raise(msg, raise_errors):
    if raise_errors:
        raise Exception(msg)
    print("🔻🔻 {}".format(msg))


def sync_global_plugin_config(filename="posthog.json"):
    from posthog.models.plugin import Plugin, PluginConfig

    did_something = False
    posthog_json = load_json_file(filename)

    # get all plugins with global configs from posthog.json
    json_plugin_configs = {}
    if posthog_json and posthog_json.get("plugins", None):
        for plugin in posthog_json["plugins"]:
            global_config = plugin.get("global", None)
            if global_config:
                json_plugin_configs[plugin["name"]] = global_config

    # what plugins actually exist in the db?
    db_plugins = {}
    for plugin in Plugin.objects.all():
        db_plugins[plugin.name] = plugin

    # get all global plugins configs from the db... delete if not in posthog.json or plugin not installed
    db_plugin_configs = {}
    for plugin_config in list(PluginConfig.objects.filter(team=None)):
        name = plugin_config.plugin.name
        if not json_plugin_configs.get(name, None) or not db_plugins.get(name, None):
            plugin_config.delete()
            did_something = True
            continue
        db_plugin_configs[name] = plugin_config

    # add new and update changed configs into the db
    for name, plugin_json in json_plugin_configs.items():
        enabled = plugin_json.get("enabled", False)
        order = plugin_json.get("order", 0)
        config = plugin_json.get("config", {})

        db_plugin_config = db_plugin_configs.get(name, None)
        if db_plugin_config:
            if (
                db_plugin_config.enabled != enabled
                or db_plugin_config.order != order
                or json.dumps(db_plugin_config.config) != json.dumps(config)
            ):
                db_plugin_config.enabled = enabled
                db_plugin_config.order = order
                db_plugin_config.config = config
                db_plugin_config.save()
                did_something = True
        elif db_plugins.get(name, None):
            PluginConfig.objects.create(
                team=None, plugin=db_plugins[name], enabled=enabled, order=order, config=config,
            )

    return did_something
