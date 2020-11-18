import base64
import io
import json
import os
import tempfile
import zipfile
from contextlib import contextmanager
from unittest import mock

from posthog.api.test.base import BaseTest
from posthog.models import Plugin, PluginConfig
from posthog.plugins.sync import sync_global_plugin_config, sync_posthog_json_plugins

from .plugin_archives import HELLO_WORLD_PLUGIN_GITHUB_ZIP


@contextmanager
def plugins_in_posthog_json(plugins):
    filename = None
    try:
        fd, filename = tempfile.mkstemp(prefix="posthog-", suffix=".json")
        os.write(fd, str.encode(json.dumps({"plugins": plugins})))
        os.close(fd)
        yield filename
    finally:
        if filename:
            os.unlink(filename)


@contextmanager
def extracted_base64_zip(base64_archive):
    tmp_folder = None
    try:
        zip_file = zipfile.ZipFile(io.BytesIO(base64.b64decode(base64_archive)), "r")
        zip_root_folder = zip_file.namelist()[0]
        tmp_folder = tempfile.TemporaryDirectory()
        zip_file.extractall(path=tmp_folder.name)
        yield os.path.join(tmp_folder.name, zip_root_folder)
    finally:
        if tmp_folder:
            tmp_folder.cleanup()


# This method will be used by the mock to replace requests.get
def mocked_requests_get(*args, **kwargs):
    class MockResponse:
        def __init__(self, base64_data, status_code):
            self.content = base64.b64decode(base64_data)
            self.status_code = status_code

        def ok(self):
            return self.status_code < 300

    if args[0] == "https://github.com/PostHog/helloworldplugin/archive/{}.zip".format(HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]):
        return MockResponse(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1], 200)

    return MockResponse(None, 404)


@mock.patch("requests.get", side_effect=mocked_requests_get)
class TestPluginsSync(BaseTest):
    def _write_json_plugins(self, plugins):
        fd, json_path = tempfile.mkstemp(prefix="posthog-", suffix=".json")
        os.write(fd, str.encode(json.dumps({"plugins": plugins})))
        os.close(fd)
        return json_path

    def test_load_plugin_local(self, mock_get):
        with extracted_base64_zip(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]) as plugin_path:
            self.assertEqual(len(Plugin.objects.all()), 0)

            with plugins_in_posthog_json([{"name": "helloworldplugin", "path": plugin_path,}]) as filename:
                sync_posthog_json_plugins(raise_errors=True, filename=filename)
                self.assertEqual(len(Plugin.objects.all()), 1)
                sync_posthog_json_plugins(raise_errors=True, filename=filename)
                self.assertEqual(len(Plugin.objects.all()), 1)

            plugin = Plugin.objects.get()
            self.assertEqual(plugin.name, "helloworldplugin")
            self.assertEqual(plugin.url, "file:{}".format(plugin_path))
            self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
            self.assertEqual(plugin.from_json, True)
            self.assertEqual(plugin.from_web, False)
            self.assertEqual(plugin.archive, None)
            self.assertEqual(plugin.config_schema["bar"]["type"], "string")
            self.assertEqual(plugin.tag, "")

            with plugins_in_posthog_json([]) as filename:
                sync_posthog_json_plugins(raise_errors=True, filename=filename)

            self.assertEqual(len(Plugin.objects.all()), 0)

    def test_load_plugin_local_if_exists_from_app(self, mock_get):
        with extracted_base64_zip(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]) as plugin_path:
            Plugin.objects.create(
                name="helloworldplugin",
                description="BAD DESCRIPTION",
                url="file:{}".format(plugin_path),
                config_schema={},
                tag="",
                from_web=True,
                from_json=False,
            )
            self.assertEqual(len(Plugin.objects.all()), 1)

            with plugins_in_posthog_json([{"name": "helloworldplugin", "path": plugin_path,}]) as filename:
                sync_posthog_json_plugins(raise_errors=True, filename=filename)
                self.assertEqual(len(Plugin.objects.all()), 1)
                sync_posthog_json_plugins(raise_errors=True, filename=filename)
                self.assertEqual(len(Plugin.objects.all()), 1)

            plugin = Plugin.objects.get()
            self.assertEqual(plugin.name, "helloworldplugin")
            self.assertEqual(plugin.url, "file:{}".format(plugin_path))
            self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
            self.assertEqual(plugin.from_json, True)
            self.assertEqual(plugin.from_web, True)
            self.assertEqual(plugin.archive, None)
            self.assertEqual(plugin.tag, "")
            self.assertEqual(plugin.config_schema["bar"]["type"], "string")

            with plugins_in_posthog_json([]) as filename:
                sync_posthog_json_plugins(raise_errors=True, filename=filename)

            self.assertEqual(len(Plugin.objects.all()), 1)

            plugin = Plugin.objects.get()
            self.assertEqual(plugin.name, "helloworldplugin")
            self.assertEqual(plugin.url, "file:{}".format(plugin_path))
            self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
            self.assertEqual(plugin.from_json, False)
            self.assertEqual(plugin.from_web, True)
            self.assertEqual(plugin.archive, None)
            self.assertEqual(plugin.tag, "")
            self.assertEqual(plugin.config_schema["bar"]["type"], "string")

    def test_load_plugin_http(self, mock_get):
        self.assertEqual(len(Plugin.objects.all()), 0)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                }
            ]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)

        plugin = Plugin.objects.get()
        self.assertEqual(plugin.name, "helloworldplugin")
        self.assertEqual(plugin.url, "https://github.com/PostHog/helloworldplugin/")
        self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
        self.assertEqual(plugin.from_json, True)
        self.assertEqual(plugin.from_web, False)
        self.assertEqual(bytes(plugin.archive), base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
        self.assertEqual(plugin.tag, HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])
        self.assertEqual(plugin.config_schema["bar"]["type"], "string")

        with plugins_in_posthog_json([]) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)

        self.assertEqual(len(Plugin.objects.all()), 0)

    def test_load_plugin_http_if_exists_from_app(self, mock_get):
        Plugin.objects.create(
            name="helloworldplugin",
            description="BAD DESCRIPTION",
            url="https://github.com/PostHog/helloworldplugin/",
            config_schema={},
            tag="BAD TAG",
            archive=bytes("blabla".encode("utf-8")),
            from_web=True,
            from_json=False,
        )
        self.assertEqual(len(Plugin.objects.all()), 1)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                }
            ]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)

        plugin = Plugin.objects.get()
        self.assertEqual(plugin.name, "helloworldplugin")
        self.assertEqual(plugin.url, "https://github.com/PostHog/helloworldplugin/")
        self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
        self.assertEqual(plugin.from_json, True)
        self.assertEqual(plugin.from_web, True)
        self.assertEqual(bytes(plugin.archive), base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
        self.assertEqual(plugin.tag, HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])
        self.assertEqual(plugin.config_schema["bar"]["type"], "string")

        with plugins_in_posthog_json([]) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)

        self.assertEqual(len(Plugin.objects.all()), 1)

        plugin = Plugin.objects.get()
        self.assertEqual(plugin.name, "helloworldplugin")
        self.assertEqual(plugin.url, "https://github.com/PostHog/helloworldplugin/")
        self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
        self.assertEqual(plugin.from_json, False)
        self.assertEqual(plugin.from_web, True)
        self.assertEqual(bytes(plugin.archive), base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
        self.assertEqual(plugin.tag, HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])
        self.assertEqual(plugin.config_schema["bar"]["type"], "string")

    def test_load_plugin_local_to_http_and_back(self, mock_get):
        with extracted_base64_zip(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]) as plugin_path:
            with plugins_in_posthog_json(
                [
                    {
                        "name": "helloworldplugin",
                        "url": "https://github.com/PostHog/helloworldplugin/",
                        "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                    }
                ]
            ) as filename:
                sync_posthog_json_plugins(raise_errors=True, filename=filename)
                self.assertEqual(len(Plugin.objects.all()), 1)

            plugin = Plugin.objects.get()
            self.assertEqual(plugin.name, "helloworldplugin")
            self.assertEqual(plugin.url, "https://github.com/PostHog/helloworldplugin/")
            self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
            self.assertEqual(plugin.from_json, True)
            self.assertEqual(plugin.from_web, False)
            self.assertEqual(bytes(plugin.archive), base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
            self.assertEqual(plugin.tag, HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])
            self.assertEqual(plugin.config_schema["bar"]["type"], "string")

            with plugins_in_posthog_json([{"name": "helloworldplugin", "path": plugin_path,}]) as filename:
                sync_posthog_json_plugins(raise_errors=True, filename=filename)
                self.assertEqual(len(Plugin.objects.all()), 1)

            plugin = Plugin.objects.get()
            self.assertEqual(plugin.name, "helloworldplugin")
            self.assertEqual(plugin.url, "file:{}".format(plugin_path))
            self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
            self.assertEqual(plugin.from_json, True)
            self.assertEqual(plugin.from_web, False)
            self.assertEqual(plugin.archive, None)
            self.assertEqual(plugin.tag, "")
            self.assertEqual(plugin.config_schema["bar"]["type"], "string")

            with plugins_in_posthog_json(
                [
                    {
                        "name": "helloworldplugin",
                        "url": "https://github.com/PostHog/helloworldplugin/",
                        "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                    }
                ]
            ) as filename:
                sync_posthog_json_plugins(raise_errors=True, filename=filename)
                self.assertEqual(len(Plugin.objects.all()), 1)

            plugin = Plugin.objects.get()
            self.assertEqual(plugin.name, "helloworldplugin")
            self.assertEqual(plugin.url, "https://github.com/PostHog/helloworldplugin/")
            self.assertEqual(plugin.description, "Greet the World and Foo a Bar, JS edition!")
            self.assertEqual(plugin.from_json, True)
            self.assertEqual(plugin.from_web, False)
            self.assertEqual(bytes(plugin.archive), base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]))
            self.assertEqual(plugin.tag, HELLO_WORLD_PLUGIN_GITHUB_ZIP[0])
            self.assertEqual(plugin.config_schema["bar"]["type"], "string")

    def test_sync_global_config(self, mock_get):
        self.assertEqual(len(Plugin.objects.all()), 0)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                }
            ]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            sync_global_plugin_config(filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            self.assertEqual(len(PluginConfig.objects.all()), 0)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                    "global": {"enabled": True, "order": 2, "config": {"bar": "foo"}},
                }
            ]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            sync_global_plugin_config(filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            self.assertEqual(len(PluginConfig.objects.all()), 1)
            plugin_config = PluginConfig.objects.get()
            self.assertEqual(plugin_config.team, None)
            self.assertEqual(plugin_config.plugin, Plugin.objects.get())
            self.assertEqual(plugin_config.enabled, True)
            self.assertEqual(plugin_config.config["bar"], "foo")
            self.assertEqual(plugin_config.order, 2)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                    "global": {"enabled": False, "order": 3, "config": {"bar": "foop"}},
                }
            ]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            sync_global_plugin_config(filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            self.assertEqual(len(PluginConfig.objects.all()), 1)
            plugin_config = PluginConfig.objects.get()
            self.assertEqual(plugin_config.team, None)
            self.assertEqual(plugin_config.plugin, Plugin.objects.get())
            self.assertEqual(plugin_config.enabled, False)
            self.assertEqual(plugin_config.config["bar"], "foop")
            self.assertEqual(plugin_config.order, 3)

        with plugins_in_posthog_json([]) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            sync_global_plugin_config(filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 0)
            self.assertEqual(len(PluginConfig.objects.all()), 0)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                    "global": {"enabled": False, "order": 3, "config": {"bar": "foop"}},
                }
            ]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            sync_global_plugin_config(filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            self.assertEqual(len(PluginConfig.objects.all()), 1)
            plugin_config = PluginConfig.objects.get()
            self.assertEqual(plugin_config.team, None)
            self.assertEqual(plugin_config.plugin, Plugin.objects.get())
            self.assertEqual(plugin_config.enabled, False)
            self.assertEqual(plugin_config.config["bar"], "foop")
            self.assertEqual(plugin_config.order, 3)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": HELLO_WORLD_PLUGIN_GITHUB_ZIP[0],
                }
            ]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            sync_global_plugin_config(filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            self.assertEqual(len(PluginConfig.objects.all()), 0)
