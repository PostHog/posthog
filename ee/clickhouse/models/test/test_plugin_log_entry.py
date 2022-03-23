from django.utils import timezone

from ee.clickhouse.sql.plugin_log_entries import INSERT_PLUGIN_LOG_ENTRY_SQL
from posthog.client import sync_execute
from posthog.models import PluginLogEntry
from posthog.models.utils import UUIDT
from posthog.test.test_plugin_log_entry import factory_test_plugin_log_entry


def plugin_log_factory_ch(
    *,
    team_id: int,
    plugin_id: int,
    plugin_config_id: int,
    source: PluginLogEntry.Source,
    type: PluginLogEntry.Type,
    message: str,
    instance_id: str
):
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


class TestEvent(factory_test_plugin_log_entry(plugin_log_factory_ch)):  # type: ignore
    pass
