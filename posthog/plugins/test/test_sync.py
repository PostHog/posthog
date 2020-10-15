import base64
import json
import os
import tempfile
from contextlib import contextmanager
from unittest import mock

from posthog.api.test.base import BaseTest
from posthog.models import Plugin
from posthog.plugins.sync import sync_posthog_json_plugins

from .plugin_archives import HELLO_WORLD_PLUGIN


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


# This method will be used by the mock to replace requests.get
def mocked_requests_get(*args, **kwargs):
    class MockResponse:
        def __init__(self, base64_data, status_code):
            self.content = base64.b64decode(base64_data)
            self.status_code = status_code

        def ok(self):
            return self.status_code < 300

    if args[0] == "https://github.com/PostHog/helloworldplugin/archive/3c4c77e7d7878e87be3c2373b658c74ec3085f49.zip":
        return MockResponse(HELLO_WORLD_PLUGIN, 200)

    return MockResponse(None, 404)


@mock.patch("requests.get", side_effect=mocked_requests_get)
class TestPluginsSync(BaseTest):
    def _write_json_plugins(self, plugins):
        fd, json_path = tempfile.mkstemp(prefix="posthog-", suffix=".json")
        os.write(fd, str.encode(json.dumps({"plugins": plugins})))
        os.close(fd)
        return json_path

    def test_load_plugin_local(self, mock_get):
        self.assertEqual(len(Plugin.objects.all()), 0)

        with plugins_in_posthog_json(
            [{"name": "helloworldplugin", "path": "../helloworldplugin/", "config": {},}]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)

        plugin = Plugin.objects.get()
        self.assertEqual(plugin.name, "helloworldplugin")
        self.assertEqual(plugin.url, "file:../helloworldplugin/")
        self.assertEqual(plugin.from_cli, True)
        self.assertEqual(plugin.from_app, False)
        self.assertEqual(plugin.archive, None)
        self.assertEqual(plugin.tag, "")

        with plugins_in_posthog_json([]) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)

        self.assertEqual(len(Plugin.objects.all()), 0)

    def test_load_plugin_local_if_exists_from_app(self, mock_get):
        Plugin.objects.create(
            name="helloworldplugin",
            description="",
            url="file:../helloworldplugin/",
            configSchema={},
            tag="",
            from_web=True,
            from_cli=False,
        )
        self.assertEqual(len(Plugin.objects.all()), 1)

        with plugins_in_posthog_json(
            [{"name": "helloworldplugin", "path": "../helloworldplugin/", "config": {},}]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)

        plugin = Plugin.objects.get()
        self.assertEqual(plugin.name, "helloworldplugin")
        self.assertEqual(plugin.url, "file:../helloworldplugin/")
        self.assertEqual(plugin.from_cli, True)
        self.assertEqual(plugin.from_app, True)
        self.assertEqual(plugin.archive, None)
        self.assertEqual(plugin.tag, "")

        with plugins_in_posthog_json([]) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)

        self.assertEqual(len(Plugin.objects.all()), 1)

        plugin = Plugin.objects.get()
        self.assertEqual(plugin.name, "helloworldplugin")
        self.assertEqual(plugin.url, "file:../helloworldplugin/")
        self.assertEqual(plugin.from_cli, False)
        self.assertEqual(plugin.from_app, True)
        self.assertEqual(plugin.archive, None)
        self.assertEqual(plugin.tag, "")

    def test_load_plugin_http(self, mock_get):
        self.assertEqual(len(Plugin.objects.all()), 0)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": "3c4c77e7d7878e87be3c2373b658c74ec3085f49",
                    "config": {},
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
        self.assertEqual(plugin.from_cli, True)
        self.assertEqual(plugin.from_app, False)
        self.assertEqual(bytes(plugin.archive), base64.b64decode(HELLO_WORLD_PLUGIN))
        self.assertEqual(plugin.tag, "3c4c77e7d7878e87be3c2373b658c74ec3085f49")

        with plugins_in_posthog_json([]) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)

        self.assertEqual(len(Plugin.objects.all()), 0)

    def test_load_plugin_http_if_exists_from_app(self, mock_get):
        Plugin.objects.create(
            name="helloworldplugin",
            description="",
            url="https://github.com/PostHog/helloworldplugin/",
            configSchema={},
            tag="BAD TAG",
            archive=bytes("blabla".encode("utf-8")),
            from_web=True,
            from_cli=False,
        )
        self.assertEqual(len(Plugin.objects.all()), 1)

        with plugins_in_posthog_json(
            [
                {
                    "name": "helloworldplugin",
                    "url": "https://github.com/PostHog/helloworldplugin/",
                    "tag": "3c4c77e7d7878e87be3c2373b658c74ec3085f49",
                    "config": {},
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
        self.assertEqual(plugin.from_cli, True)
        self.assertEqual(plugin.from_app, True)
        self.assertEqual(bytes(plugin.archive), base64.b64decode(HELLO_WORLD_PLUGIN))
        self.assertEqual(plugin.tag, "3c4c77e7d7878e87be3c2373b658c74ec3085f49")

        with plugins_in_posthog_json([]) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)

        self.assertEqual(len(Plugin.objects.all()), 1)

        plugin = Plugin.objects.get()
        self.assertEqual(plugin.name, "helloworldplugin")
        self.assertEqual(plugin.url, "https://github.com/PostHog/helloworldplugin/")
        self.assertEqual(plugin.from_cli, False)
        self.assertEqual(plugin.from_app, True)
        self.assertEqual(bytes(plugin.archive), base64.b64decode(HELLO_WORLD_PLUGIN))
        self.assertEqual(plugin.tag, "3c4c77e7d7878e87be3c2373b658c74ec3085f49")
