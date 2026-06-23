from collections.abc import Callable

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig
from posthog.tasks.remote_config import (
    cleanup_stale_remote_config_expiry_tracking_task,
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


class TestRemoteConfigCacheTasks(BaseTest):
    @parameterized.expand(
        [
            (
                "refresh",
                refresh_expiring_remote_config_cache_entries,
                "posthog.tasks.remote_config.refresh_expiring_caches",
            ),
            (
                "cleanup",
                cleanup_stale_remote_config_expiry_tracking_task,
                "posthog.tasks.remote_config.cleanup_stale_expiry_tracking",
            ),
        ]
    )
    def test_task_skips_work_when_flags_redis_url_unset(
        self, _name: str, task: Callable[[], None], inner_path: str
    ) -> None:
        with override_settings(FLAGS_REDIS_URL=""), patch(inner_path) as mock_inner:
            task()
        mock_inner.assert_not_called()

    def test_refresh_runs_work_when_flags_redis_url_set(self) -> None:
        with (
            override_settings(FLAGS_REDIS_URL="redis://test:6379/0"),
            patch("posthog.tasks.remote_config.refresh_expiring_caches", return_value=(0, 0)) as mock_refresh,
            patch("posthog.tasks.remote_config.get_cache_stats", return_value={}),
        ):
            refresh_expiring_remote_config_cache_entries()
        mock_refresh.assert_called_once_with(ttl_threshold_hours=24)

    def test_cleanup_runs_work_when_flags_redis_url_set(self) -> None:
        with (
            override_settings(FLAGS_REDIS_URL="redis://test:6379/0"),
            patch("posthog.tasks.remote_config.cleanup_stale_expiry_tracking", return_value=0) as mock_cleanup,
        ):
            cleanup_stale_remote_config_expiry_tracking_task()
        mock_cleanup.assert_called_once_with()
