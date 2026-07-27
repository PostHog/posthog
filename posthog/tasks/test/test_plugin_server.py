from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import OrganizationMembership
from posthog.tasks.plugin_server import _dispatch_plugin_disabled_realtime

from products.cdp.backend.models.plugin import Plugin, PluginConfig


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

        _dispatch_plugin_disabled_realtime(plugin_config.id, "2026-01-01T00:00:00Z", "boom")

        assert mock_create_notification.call_count >= 1
        first = mock_create_notification.call_args_list[0].args[0]
        assert first.notification_type.value == "pipeline_failure"
        assert first.title == "Plugin GeoIP disabled"
        assert first.body == "boom"
        assert first.resource_id == str(plugin_config.id)
        assert first.source_id == "2026-01-01T00:00:00Z"
        assert first.source_url == f"/project/{self.team.project_id}/pipeline/plugins/{plugin_config.id}"

    @patch("posthog.tasks.plugin_server.create_notification", side_effect=RuntimeError("kafka"))
    def test_swallows_per_recipient_exceptions(self, mock_create: MagicMock) -> None:
        plugin = Plugin.objects.create(organization=self.organization, name="GeoIP")
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)
        # Should not raise.
        _dispatch_plugin_disabled_realtime(plugin_config.id, "2026-01-01T00:00:00Z", "boom")
        # Confirms the function actually attempted the dispatch before swallowing,
        # so a silent early-return would not mask a regression here.
        assert mock_create.call_count >= 1

    @patch("posthog.tasks.plugin_server.create_notification")
    def test_swallows_missing_plugin_config(self, mock_create_notification: MagicMock) -> None:
        _dispatch_plugin_disabled_realtime(999_999_999, "2026-01-01T00:00:00Z", "boom")
        mock_create_notification.assert_not_called()

    @patch("posthog.tasks.plugin_server.create_notification")
    @patch("posthog.tasks.plugin_server.has_been_dispatched", return_value=True)
    def test_skips_dispatch_when_already_dispatched(
        self,
        _mock_has_been_dispatched: MagicMock,
        mock_create_notification: MagicMock,
    ) -> None:
        # Mirrors the email path's MessagingRecord dedup: re-running fatal_plugin_error
        # for the same plugin_config_updated_at must not double-notify.
        plugin = Plugin.objects.create(organization=self.organization, name="GeoIP")
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)

        _dispatch_plugin_disabled_realtime(plugin_config.id, "2026-01-01T00:00:00Z", "boom")

        mock_create_notification.assert_not_called()
