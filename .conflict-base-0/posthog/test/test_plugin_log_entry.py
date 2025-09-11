from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.models import Plugin, PluginConfig
from posthog.models.plugin import PluginLogEntrySource, PluginLogEntryType, fetch_plugin_log_entries
from posthog.models.utils import UUIDT


def create_plugin_log_entry(
    *,
    team_id: int,
    plugin_id: int,
    plugin_config_id: int,
    source: PluginLogEntrySource,
    type: PluginLogEntryType,
    message: str,
    instance_id: str,
):
    from posthog.clickhouse.plugin_log_entries import INSERT_PLUGIN_LOG_ENTRY_SQL

    sync_execute(
        INSERT_PLUGIN_LOG_ENTRY_SQL,
        {
            "id": UUIDT(),
            "team_id": team_id,
            "plugin_id": plugin_id,
            "plugin_config_id": plugin_config_id,
            "source": source,
            "type": type,
            "instance_id": instance_id,
            "message": message,
            "timestamp": timezone.now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
        },
    )


class TestPluginLogEntry(BaseTest):
    def test_simple_log_is_fetched(self):
        plugin_server_instance_id = str(UUIDT())

        some_plugin: Plugin = Plugin.objects.create(organization=self.organization)
        some_plugin_config: PluginConfig = PluginConfig.objects.create(plugin=some_plugin, order=1)

        create_plugin_log_entry(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            plugin_config_id=some_plugin_config.pk,
            source=PluginLogEntrySource.CONSOLE,
            type=PluginLogEntryType.INFO,
            message="Something happened!",
            instance_id=plugin_server_instance_id,
        )

        results = fetch_plugin_log_entries(
            plugin_config_id=some_plugin_config.pk,
            after=timezone.datetime.min,
            before=timezone.now() + timezone.timedelta(seconds=5),
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].message, "Something happened!")

    def test_log_search_works(self):
        plugin_server_instance_id = str(UUIDT())

        some_plugin: Plugin = Plugin.objects.create(organization=self.organization)
        some_plugin_config: PluginConfig = PluginConfig.objects.create(plugin=some_plugin, order=1)

        create_plugin_log_entry(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            plugin_config_id=some_plugin_config.pk,
            source=PluginLogEntrySource.CONSOLE,
            type=PluginLogEntryType.INFO,
            message="Something happened!",
            instance_id=plugin_server_instance_id,
        )
        create_plugin_log_entry(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            plugin_config_id=some_plugin_config.pk,
            source=PluginLogEntrySource.CONSOLE,
            type=PluginLogEntryType.ERROR,
            message="Random error",
            instance_id=plugin_server_instance_id,
        )

        results = fetch_plugin_log_entries(plugin_config_id=some_plugin_config.pk, search="somethinG")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].message, "Something happened!")

    def test_log_type_filter_works(self):
        plugin_server_instance_id = str(UUIDT())

        some_plugin: Plugin = Plugin.objects.create(organization=self.organization)
        some_plugin_config: PluginConfig = PluginConfig.objects.create(plugin=some_plugin, order=1)

        create_plugin_log_entry(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            plugin_config_id=some_plugin_config.pk,
            source=PluginLogEntrySource.CONSOLE,
            type=PluginLogEntryType.INFO,
            message="Something happened!",
            instance_id=plugin_server_instance_id,
        )
        create_plugin_log_entry(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            plugin_config_id=some_plugin_config.pk,
            source=PluginLogEntrySource.CONSOLE,
            type=PluginLogEntryType.ERROR,
            message="Random error",
            instance_id=plugin_server_instance_id,
        )
        create_plugin_log_entry(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            plugin_config_id=some_plugin_config.pk,
            source=PluginLogEntrySource.CONSOLE,
            type=PluginLogEntryType.DEBUG,
            message="debug message",
            instance_id=plugin_server_instance_id,
        )

        results = fetch_plugin_log_entries(
            plugin_config_id=some_plugin_config.pk,
            type_filter=[PluginLogEntryType.ERROR, PluginLogEntryType.DEBUG],
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].message, "debug message")
        self.assertEqual(results[1].message, "Random error")

    def test_log_limit_works(self):
        plugin_server_instance_id = str(UUIDT())

        some_plugin: Plugin = Plugin.objects.create(organization=self.organization)
        some_plugin_config: PluginConfig = PluginConfig.objects.create(plugin=some_plugin, order=1)

        create_plugin_log_entry(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            plugin_config_id=some_plugin_config.pk,
            source=PluginLogEntrySource.CONSOLE,
            type=PluginLogEntryType.INFO,
            message="Something happened!",
            instance_id=plugin_server_instance_id,
        )
        create_plugin_log_entry(
            team_id=self.team.pk,
            plugin_id=some_plugin.pk,
            plugin_config_id=some_plugin_config.pk,
            source=PluginLogEntrySource.CONSOLE,
            type=PluginLogEntryType.ERROR,
            message="Random error",
            instance_id=plugin_server_instance_id,
        )

        results = fetch_plugin_log_entries(plugin_config_id=some_plugin_config.pk, limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].message, "Random error")
