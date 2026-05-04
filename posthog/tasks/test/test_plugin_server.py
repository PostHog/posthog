from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import OrganizationMembership
from posthog.models.plugin import Plugin, PluginConfig
from posthog.tasks.plugin_server import _dispatch_plugin_disabled_realtime


class TestDispatchPluginDisabledRealtime(BaseTest):
    @patch("posthog.tasks.plugin_server.create_notification")
    def test_dispatches_one_notification_per_membership(self, mock_create_notification: MagicMock) -> None:
        plugin = Plugin.objects.create(organization=self.organization, name="GeoIP")
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)
        user2 = self._create_user("subscriber@test.com")
        OrganizationMembership.objects.get_or_create(
            organization=self.organization,
            user=user2,
            defaults={"level": OrganizationMembership.Level.MEMBER},
        )

        _dispatch_plugin_disabled_realtime(plugin_config.id, "boom")

        assert mock_create_notification.call_count >= 1
        first = mock_create_notification.call_args_list[0].args[0]
        assert first.notification_type.value == "pipeline_failure"
        assert first.title == "Plugin GeoIP disabled"
        assert first.body == "boom"
        assert first.resource_id == str(plugin_config.id)
        assert first.source_url == f"/project/{self.team.project_id}/pipeline/transformations/{plugin_config.id}"

    @patch("posthog.tasks.plugin_server.create_notification", side_effect=RuntimeError("kafka"))
    def test_swallows_per_recipient_exceptions(self, _mock_create: MagicMock) -> None:
        plugin = Plugin.objects.create(organization=self.organization, name="GeoIP")
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)
        # Should not raise.
        _dispatch_plugin_disabled_realtime(plugin_config.id, "boom")

    @patch("posthog.tasks.plugin_server.create_notification")
    def test_swallows_missing_plugin_config(self, mock_create_notification: MagicMock) -> None:
        _dispatch_plugin_disabled_realtime(999_999_999, "boom")
        mock_create_notification.assert_not_called()
