from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models.remote_config import RemoteConfig
from posthog.storage.cache_expiry_manager import CacheRefreshCounts
from posthog.storage.remote_config_cache import (
    cleanup_stale_expiry_tracking,
    refresh_expiring_caches,
    update_remote_config_cache,
)


class TestUpdateRemoteConfigCache(BaseTest):
    def setUp(self):
        super().setUp()
        RemoteConfig.objects.filter(team=self.team).delete()
        self.remote_config = RemoteConfig.objects.create(
            team=self.team,
            config={"token": self.team.api_token, "hasFeatureFlags": False},
        )

    @patch("posthog.storage.remote_config_cache.remote_config_hypercache")
    def test_writes_redis_only_with_expiry_tracking(self, mock_hypercache):
        result = update_remote_config_cache(self.team)

        assert result is True
        mock_hypercache.set_cache_value_redis_only.assert_called_once()
        args, kwargs = mock_hypercache.set_cache_value_redis_only.call_args
        # Keyed by Team so expiry tracking fires; re-stamps the persisted config; skips S3.
        assert args[0] == self.team
        assert args[1] == self.remote_config.config
        assert kwargs["track_expiry"] is True

    @patch("posthog.storage.remote_config_cache.remote_config_hypercache")
    def test_skips_empty_config(self, mock_hypercache):
        self.remote_config.config = {}
        self.remote_config.save(update_fields=["config"])

        result = update_remote_config_cache(self.team)

        assert result is False
        mock_hypercache.set_cache_value_redis_only.assert_not_called()

    @patch("posthog.storage.remote_config_cache.remote_config_hypercache")
    def test_skips_when_no_remote_config_row(self, mock_hypercache):
        self.remote_config.delete()

        result = update_remote_config_cache(self.team)

        assert result is False
        mock_hypercache.set_cache_value_redis_only.assert_not_called()


class TestRefreshExpiringRemoteConfigCaches(BaseTest):
    @patch("posthog.storage.remote_config_cache.remote_config_hypercache")
    @patch("posthog.storage.cache_expiry_manager.get_client")
    @patch("posthog.storage.cache_expiry_manager.time")
    def test_refreshes_only_expiring_entries(self, mock_time, mock_get_client, mock_hypercache):
        RemoteConfig.objects.filter(team=self.team).delete()
        RemoteConfig.objects.create(team=self.team, config={"token": self.team.api_token})

        mock_time.time.return_value = 1_000_000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = [self.team.api_token.encode()]

        counts = refresh_expiring_caches(ttl_threshold_hours=24)

        assert counts == CacheRefreshCounts(successful=1, failed=0)
        mock_redis.zrangebyscore.assert_called_once_with(
            "remote_config_cache_expiry",
            "-inf",
            1_000_000 + (24 * 3600),
            start=0,
            num=5000,
        )
        # The expiring team's entry was re-stamped redis-only with expiry tracking.
        mock_hypercache.set_cache_value_redis_only.assert_called_once()
        _, kwargs = mock_hypercache.set_cache_value_redis_only.call_args
        assert kwargs["track_expiry"] is True

    # Patched at the Pushgateway seam rather than at push_refresh_metrics, so the
    # shared helper still runs and the backlog it counts is what gets asserted.
    @patch("posthog.storage.cache_expiry_manager.push_hypercache_teams_processed_metrics")
    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_an_empty_run_still_reports_its_counts_and_backlog(self, mock_get_client, mock_push):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []
        mock_redis.zcount.return_value = 0

        assert refresh_expiring_caches(ttl_threshold_hours=24) == CacheRefreshCounts(successful=0, failed=0)

        # Pushgateway keeps serving the last value pushed, so a run that returned before
        # pushing would leave a drained backlog reading as the last busy run's count.
        push_kwargs = mock_push.call_args.kwargs
        assert push_kwargs["successful"] == 0
        assert push_kwargs["failed"] == 0
        assert push_kwargs["expiry_backlog"] == 0


class TestCleanupStaleRemoteConfigExpiryTracking(BaseTest):
    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_removes_only_entries_for_deleted_teams(self, mock_get_client):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        # One live team (kept) and one stale token (removed).
        mock_redis.zrange.return_value = [self.team.api_token.encode(), b"phc_does_not_exist"]
        mock_redis.zrem.return_value = 1

        removed = cleanup_stale_expiry_tracking()

        assert removed == 1
        mock_redis.zrem.assert_called_once_with("remote_config_cache_expiry", "phc_does_not_exist")
