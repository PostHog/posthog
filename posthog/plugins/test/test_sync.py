import json
import os
import tempfile
from contextlib import contextmanager

from posthog.api.test.base import BaseTest
from posthog.models import Plugin
from posthog.plugins.sync import sync_posthog_json_plugins


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


class TestPluginsSync(BaseTest):
    def _write_json_plugins(self, plugins):
        fd, json_path = tempfile.mkstemp(prefix="posthog-", suffix=".json")
        os.write(fd, str.encode(json.dumps({"plugins": plugins})))
        os.close(fd)
        return json_path

    def test_load_plugin(self):
        self.assertEqual(len(Plugin.objects.all()), 0)

        with plugins_in_posthog_json(
            [
                {
                    "name": "posthog-currency-normalization-plugin",
                    "path": "../posthog-currency-normalization-plugin/",
                    "config": {},
                }
            ]
        ) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)

            sync_posthog_json_plugins(raise_errors=True, filename=filename)
            self.assertEqual(len(Plugin.objects.all()), 1)

        plugin = Plugin.objects.get()
        self.assertEqual(plugin.name, "posthog-currency-normalization-plugin")
        self.assertEqual(plugin.url, "file:../posthog-currency-normalization-plugin/")
        self.assertEqual(plugin.from_cli, True)
        self.assertEqual(plugin.from_web, False)
        self.assertEqual(plugin.archive, None)
        self.assertEqual(plugin.tag, "")

        with plugins_in_posthog_json([]) as filename:
            sync_posthog_json_plugins(raise_errors=True, filename=filename)

        self.assertEqual(len(Plugin.objects.all()), 0)
