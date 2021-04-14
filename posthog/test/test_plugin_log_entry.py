from django.utils import timezone

from posthog.models import Plugin, PluginLogEntry
from posthog.models.plugin import fetch_plugin_log_entries
from posthog.models.utils import UUIDT
from posthog.test.base import BaseTest


class TestPluginLogEntry(BaseTest):
    def test_simple_log_is_fetched(self):
        plugin_server_instance_id = str(UUIDT())

        some_plugin = Plugin.objects.create(organization=self.organization)
        PluginLogEntry.objects.create(
            team=self.team,
            plugin=some_plugin,
            type=PluginLogEntry.Type.INFO,
            message="Something happened!",
            instance_id=plugin_server_instance_id,
        )

        with self.assertNumQueries(1):
            results = fetch_plugin_log_entries(
                team_id=self.team.pk,
                plugin_id=some_plugin.pk,
                after=timezone.datetime.min,
                before=timezone.now() + timezone.timedelta(seconds=5),
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].message, "Something happened!")
