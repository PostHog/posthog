from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig
from posthog.tasks.remote_config import (
    refresh_expiring_remote_config_cache_entries,
    sync_all_remote_configs,
    update_team_remote_config,
)


class TestRemoteConfig(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )
        self.other_team_1 = team

        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project 2",
        )
        self.other_team_2 = team

        # Force synchronous RemoteConfig creation for tests since signals are async now
        from posthog.tasks.remote_config import update_team_remote_config

        for team in [self.team, self.other_team_1, self.other_team_2]:
            try:
                RemoteConfig.objects.get(team=team)
            except RemoteConfig.DoesNotExist:
                update_team_remote_config(team.id)

    def test_sync_task_syncs_all_remote_configs(self) -> None:
        # Delete one teams config
        remote_config_deleted = RemoteConfig.objects.get(team=self.team)
        remote_config_deleted_synced_at = remote_config_deleted.synced_at
        remote_config_deleted.delete()

        configs = RemoteConfig.objects.all()
        assert len(configs) == 2

        # Modify the other team's config (indicate something didn't get synced properly)
        remote_config_1 = RemoteConfig.objects.get(team=self.other_team_1)
        remote_config_1.config["token"] = "MODIFIED"
        remote_config_1.save()
        remote_config_1_synced_at = remote_config_1.synced_at

        # No modifications to this one
        remote_config_2 = RemoteConfig.objects.get(team=self.other_team_2)
        remote_config_2_synced_at = remote_config_2.synced_at

        sync_all_remote_configs()

        configs = RemoteConfig.objects.all()
        assert len(configs) == 3

        # This one is deleted so should be synced
        assert RemoteConfig.objects.get(team=self.team).synced_at > remote_config_deleted_synced_at  # type: ignore
        # This one is modified so should be synced
        assert RemoteConfig.objects.get(team=self.other_team_1).synced_at > remote_config_1_synced_at  # type: ignore
        # This one is unchanged so should not be synced
        assert RemoteConfig.objects.get(team=self.other_team_2).synced_at == remote_config_2_synced_at

    @patch.object(RemoteConfig, "sync")
    def test_update_team_remote_config_forwards_bypass_recordings_quota_cache(self, mock_sync: MagicMock) -> None:
        """End-to-end coverage that the task forwards the bypass kwarg to `RemoteConfig.sync`."""
        update_team_remote_config(self.team.id, bypass_recordings_quota_cache=True)
        mock_sync.assert_called_once_with(bypass_recordings_quota_cache=True)

        mock_sync.reset_mock()
        update_team_remote_config(self.team.id)
        mock_sync.assert_called_once_with(bypass_recordings_quota_cache=False)

    @patch("posthog.tasks.remote_config.refresh_expiring_remote_config_caches")
    @patch("posthog.tasks.remote_config.settings")
    def test_refresh_task_delegates_to_refresh_expiring_remote_config_caches(
        self, mock_settings: MagicMock, mock_refresh: MagicMock
    ) -> None:
        """
        Regression for #65026: the hourly refresh job must call into the
        cache-expiry manager with the 24h threshold so entries are rewritten
        before their 30-day TTL elapses. Mocked at the import boundary so this
        runs without Redis.
        """
        mock_settings.FLAGS_REDIS_URL = "redis://example/0"
        mock_refresh.return_value = (5, 0)

        refresh_expiring_remote_config_cache_entries()

        mock_refresh.assert_called_once_with(ttl_threshold_hours=24)

    @patch("posthog.tasks.remote_config.refresh_expiring_remote_config_caches")
    @patch("posthog.tasks.remote_config.settings")
    def test_refresh_task_skips_when_flags_redis_unconfigured(
        self, mock_settings: MagicMock, mock_refresh: MagicMock
    ) -> None:
        """No-op when `FLAGS_REDIS_URL` is unset — matches the team-metadata refresh task."""
        mock_settings.FLAGS_REDIS_URL = None

        refresh_expiring_remote_config_cache_entries()

        mock_refresh.assert_not_called()
