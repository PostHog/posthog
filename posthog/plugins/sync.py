import json
import os
from typing import Any, Dict, List, Optional, Type

from .utils import download_plugin_github_zip, load_json_file, load_json_zip_bytes


def sync_posthog_json_plugins(raise_errors=False, filename="posthog.json"):
    from posthog.models.plugin import Plugin

    json_plugins = get_json_plugins(raise_errors=raise_errors, filename=filename)

    config_plugins: Dict[str, Dict[str, Any]] = {}

    for plugin in json_plugins:
        if plugin and plugin.get("name", None):
            config_plugins[plugin["name"]] = plugin

    db_plugins = {}
    for plugin in list(Plugin.objects.all()):
        # was added from the CLI, but no longer requested
        if plugin.from_cli and not config_plugins.get(plugin.name, None):
            if plugin.from_web:
                plugin.from_cli = False
                plugin.save()
            else:
                plugin.delete()
                continue
        db_plugins[plugin.name] = plugin

    for name, config_plugin in config_plugins.items():
        db_plugin = db_plugins.get(name, None)
        if not db_plugin:
            create_plugin_from_config(config_plugin)
        elif not config_and_db_plugin_in_sync(config_plugin, db_plugin):
            update_plugin_from_config(db_plugin, config_plugin)


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
        configSchema=config_schema,
        from_cli=True,
    )


def config_and_db_plugin_in_sync(config_plugin, db_plugin):
    url = config_plugin.get("url", "file:{}".format(config_plugin.get("path", "")))

    return (
        not url.startswith("file:")
        and db_plugin.from_cli
        and db_plugin.url == url
        and db_plugin.tag == config_plugin.get("tag", "")
    )


def update_plugin_from_config(db_plugin, config_plugin):
    db_plugin.from_cli = True
    new_url = config_plugin.get("url", "file:{}".format(config_plugin.get("path", "")))
    new_tag = config_plugin.get("tag", "")

    if db_plugin.url.startswith("file:") or new_url != db_plugin.url or new_tag != db_plugin.tag:
        db_plugin.url = new_url
        db_plugin.tag = new_tag
        if db_plugin.url.startswith("file:"):
            json = load_json_file(os.path.join(db_plugin.url.replace("file:", "", 1), "plugin.json"))
            if json:
                db_plugin.description = json["description"]
                db_plugin.configSchema = json["config"]
        else:
            db_plugin.archive = download_plugin_github_zip(db_plugin.url, db_plugin.tag)
            json = load_json_zip_bytes(db_plugin.archive, "plugin.json")
            if json:
                db_plugin.description = json["description"]
                db_plugin.configSchema = json["config"]

    db_plugin.save()


def print_or_raise(msg, raise_errors):
    if raise_errors:
        raise Exception(msg)
    print("🔻🔻 {}".format(msg))
