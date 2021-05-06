from django.utils import timezone

from posthog.models import Plugin, PluginConfig, PluginLogEntry
from posthog.models.utils import UUIDT
from posthog.tasks.delete_old_plugin_logs import delete_old_plugin_logs
from posthog.test.base import APIBaseTest


class TestDeleteOldPluginLogs(APIBaseTest):
    def test_old_logs_are_deleted_while_newer_ones_kept(self) -> None:
        plugin_server_instance_id = str(UUIDT())
        now = timezone.now()

        some_plugin: Plugin = Plugin.objects.create(organization=self.organization)
        some_plugin_config: PluginConfig = PluginConfig.objects.create(plugin=some_plugin, order=1)

        for days_before in [0, 2, 6, 9, 31]:
            PluginLogEntry.objects.create(
                team_id=self.team.pk,
                plugin_id=some_plugin.pk,
                plugin_config_id=some_plugin_config.pk,
                type=PluginLogEntry.Type.INFO,
                message="Test",
                instance_id=plugin_server_instance_id,
                timestamp=now - timezone.timedelta(days_before),
            )

        self.assertEqual(PluginLogEntry.objects.count(), 5)

        delete_old_plugin_logs()

        self.assertEqual(PluginLogEntry.objects.count(), 3)
