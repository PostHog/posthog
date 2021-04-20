from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.plugin_log_entries import INSERT_PLUGIN_LOG_ENTRY_SQL
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models import Plugin, PluginLogEntry
from posthog.models.plugin import fetch_plugin_log_entries
from posthog.models.utils import UUIDT
from posthog.test.test_plugin_log_entry import TestPluginLogEntry


class TestClickhousePluginLogEntry(ClickhouseTestMixin, TestPluginLogEntry):
    def test_simple_log_is_fetched(self):
        plugin_server_instance_id = str(UUIDT())

        some_plugin = Plugin.objects.create(organization=self.organization)

        sync_execute(
            INSERT_PLUGIN_LOG_ENTRY_SQL,
            {
                "id": UUIDT(),
                "team_id": self.team.pk,
                "plugin_id": some_plugin.pk,
                "type": PluginLogEntry.Type.INFO,
                "instance_id": plugin_server_instance_id,
                "message": "Something occured!",
                "timestamp": timezone.now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
            },
        )

        results = fetch_plugin_log_entries(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            after=timezone.datetime.min,
            before=timezone.now() + timezone.timedelta(seconds=5),
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].message, "Something occured!")
