from typing import Callable

from django.utils import timezone

from posthog.models import Plugin, PluginLogEntry
from posthog.models.plugin import fetch_plugin_log_entries
from posthog.models.utils import UUIDT
from posthog.test.base import BaseTest


def factory_test_plugin_log_entry(plugin_log_entry_factory: Callable):
    class TestPluginLogEntry(BaseTest):
        def test_simple_log_is_fetched(self):
            plugin_server_instance_id = str(UUIDT())

            some_plugin: Plugin = Plugin.objects.create(organization=self.organization)
            plugin_log_entry_factory(
                team_id=self.team.pk,
                plugin_id=some_plugin.pk,
                type=PluginLogEntry.Type.INFO,
                message="Something happened!",
                instance_id=plugin_server_instance_id,
            )

            results = fetch_plugin_log_entries(
                team_id=self.team.pk,
                plugin_id=some_plugin.pk,
                after=timezone.datetime.min,
                before=timezone.now() + timezone.timedelta(seconds=5),
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].message, "Something happened!")

        def test_log_search_works(self):
            plugin_server_instance_id = str(UUIDT())

            some_plugin: Plugin = Plugin.objects.create(organization=self.organization)
            plugin_log_entry_factory(
                team_id=self.team.pk,
                plugin_id=some_plugin.pk,
                type=PluginLogEntry.Type.INFO,
                message="Something happened!",
                instance_id=plugin_server_instance_id,
            )
            plugin_log_entry_factory(
                team_id=self.team.pk,
                plugin_id=some_plugin.pk,
                type=PluginLogEntry.Type.ERROR,
                message="Random error",
                instance_id=plugin_server_instance_id,
            )

            results = fetch_plugin_log_entries(team_id=self.team.pk, plugin_id=some_plugin.pk, search="somethinG")

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].message, "Something happened!")

        def test_log_limit_works(self):
            plugin_server_instance_id = str(UUIDT())

            some_plugin: Plugin = Plugin.objects.create(organization=self.organization)
            plugin_log_entry_factory(
                team_id=self.team.pk,
                plugin_id=some_plugin.pk,
                type=PluginLogEntry.Type.INFO,
                message="Something happened!",
                instance_id=plugin_server_instance_id,
            )
            plugin_log_entry_factory(
                team_id=self.team.pk,
                plugin_id=some_plugin.pk,
                type=PluginLogEntry.Type.ERROR,
                message="Random error",
                instance_id=plugin_server_instance_id,
            )

            results = fetch_plugin_log_entries(team_id=self.team.pk, plugin_id=some_plugin.pk, limit=1)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].message, "Random error")

    return TestPluginLogEntry


def plugin_log_factory_pg(*, team_id: int, plugin_id: int, type: PluginLogEntry.Type, message: str, instance_id: str):
    PluginLogEntry.objects.create(
        team_id=team_id, plugin_id=plugin_id, type=type, message=message, instance_id=instance_id,
    )


class TestEvent(factory_test_plugin_log_entry(plugin_log_factory_pg)):  # type: ignore
    pass
