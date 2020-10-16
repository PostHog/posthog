import base64
from typing import Any, Dict

from django.utils.timezone import now

from posthog.api.test.base import BaseTest
from posthog.models import Event, Person, Plugin, PluginConfig
from posthog.plugins import Plugins
from posthog.tasks.process_event import process_event

from .plugin_archives import HELLO_WORLD_PLUGIN

# TODO: tests to write
# - broken tag
# - broken zip
# - load from filesystem
# - no requirements.txt in zip
# - no requirements.txt in local path
# - bad code in __init__.py
# - filtering out events by not returing them
# - cache in plugins
# - requirements are loaded


class TestPlugins(BaseTest):
    def _create_event(self, properties: Dict[str, Any] = {"whatever": "true"}):
        process_event(
            "plugin_test_distinct_id",
            "",
            "",
            {"event": "$pageview", "properties": properties.copy(),},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )

    def _create_plugin(self, TEMPLATE):
        return Plugin.objects.create(
            name="helloworldplugin",
            description="Hello World Plugin that runs in test mode",
            url="https://github.com/PostHog/helloworldplugin",
            config_schema={
                "bar": {"name": "What's in the bar?", "type": "string", "default": "baz", "required": False}
            },
            tag=TEMPLATE[0],
            archive=base64.b64decode(TEMPLATE[1]),
            from_web=True,
            from_json=False,
        )

    def test_load_plugin(self):
        Person.objects.create(team=self.team, distinct_ids=["plugin_test_distinct_id"])

        self._create_event()

        event = Event.objects.get()
        self.assertEqual(event.event, "$pageview")
        self.assertEqual(event.properties.get("bar", None), None)

        plugin = self._create_plugin(HELLO_WORLD_PLUGIN)
        plugin_config = PluginConfig.objects.create(
            team=self.team, plugin=plugin, enabled=True, order=0, config={"bar": "foo"},
        )

        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)

        Plugins().reload_plugins()

        self._create_event()

        events = Event.objects.all()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].properties.get("hello", None), None)
        self.assertEqual(events[0].properties.get("bar", None), None)
        self.assertEqual(events[1].properties.get("hello", None), "world")
        self.assertEqual(events[1].properties.get("bar", None), "foo")

        plugin_config.config["bar"] = "foobar"
        plugin_config.save()

        Plugins().reload_plugins()

        self._create_event()

        events = Event.objects.all()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[2].properties.get("bar", None), "foobar")

        plugin_config.delete()
        plugin.delete()

        Plugins().reload_plugins()

        self._create_event()

        events = Event.objects.all()
        self.assertEqual(len(events), 4)
        self.assertEqual(events[3].properties.get("bar", None), None)

    def test_load_global_plugin(self):
        Person.objects.create(team=self.team, distinct_ids=["plugin_test_distinct_id"])

        self._create_event()

        event = Event.objects.get()
        self.assertEqual(event.event, "$pageview")
        self.assertEqual(event.properties.get("bar", None), None)

        plugin = self._create_plugin(HELLO_WORLD_PLUGIN)
        plugin_config = PluginConfig.objects.create(
            team=None, plugin=plugin, enabled=True, order=0, config={"bar": "foo"},
        )

        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 1)

        Plugins().reload_plugins()

        self._create_event()

        events = Event.objects.all()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].properties.get("hello", None), None)
        self.assertEqual(events[0].properties.get("bar", None), None)
        self.assertEqual(events[1].properties.get("hello", None), "world")
        self.assertEqual(events[1].properties.get("bar", None), "foo")

        plugin_config.config["bar"] = "foobar"
        plugin_config.save()

        Plugins().reload_plugins()

        self._create_event()

        events = Event.objects.all()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[2].properties.get("bar", None), "foobar")

        plugin_config.delete()
        plugin.delete()

        Plugins().reload_plugins()

        self._create_event()

        events = Event.objects.all()
        self.assertEqual(len(events), 4)
        self.assertEqual(events[3].properties.get("bar", None), None)

    def test_global_plugin_takes_precedence(self):
        self.assertEqual(Plugin.objects.count(), 0)
        Person.objects.create(team=self.team, distinct_ids=["plugin_test_distinct_id"])

        self._create_event()

        event = Event.objects.get()
        self.assertEqual(event.event, "$pageview")
        self.assertEqual(event.properties.get("bar", None), None)

        plugin = self._create_plugin(HELLO_WORLD_PLUGIN)
        self.assertEqual(Plugin.objects.count(), 1)
        local_plugin_config = PluginConfig.objects.create(
            team=self.team, plugin=plugin, enabled=True, order=2, config={"bar": "foo_local"},
        )
        global_plugin_config = PluginConfig.objects.create(
            team=None, plugin=plugin, enabled=True, order=1, config={"bar": "foo_global"},
        )

        self.assertEqual(Plugin.objects.count(), 1)
        self.assertEqual(PluginConfig.objects.count(), 2)

        Plugins().reload_plugins()

        self._create_event()

        events = Event.objects.all()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].properties.get("hello", None), None)
        self.assertEqual(events[0].properties.get("bar", None), None)
        self.assertEqual(events[1].properties.get("hello", None), "world")
        self.assertEqual(events[1].properties.get("bar", None), "foo_global")

        local_plugin_config.delete()

        Plugins().reload_plugins()

        self._create_event()

        events = Event.objects.all()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[2].properties.get("bar", None), "foo_global")
