"""
Tests for HyperCache management operations.

Covers:
- Django key prefix extraction for Redis patterns
- Redis URL routing for dedicated caches
- Cache invalidation and stats operations
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.storage.hypercache import HyperCache
from posthog.storage.hypercache_manager import (
    HyperCacheManagementConfig,
    get_cache_stats,
    invalidate_all_caches,
    push_hypercache_stats_metrics,
)


def create_test_hypercache(
    namespace: str = "test_namespace",
    value: str = "test_value",
    token_based: bool = False,
    expiry_sorted_set_key: str = "test_cache_expiry",
) -> HyperCache:
    """Create a test HyperCache with minimal setup."""

    def load_fn(team):
        return {"test": "data"}

    return HyperCache(
        namespace=namespace,
        value=value,
        load_fn=load_fn,
        token_based=token_based,
        expiry_sorted_set_key=expiry_sorted_set_key,
    )


def create_test_config(
    namespace: str = "test_namespace",
    value: str = "test_value",
    token_based: bool = False,
) -> HyperCacheManagementConfig:
    """Create a test HyperCacheManagementConfig with minimal setup."""

    def update_fn(team, ttl=None):
        return True

    hypercache = create_test_hypercache(
        namespace=namespace,
        value=value,
        token_based=token_based,
    )

    return HyperCacheManagementConfig(
        hypercache=hypercache,
        update_fn=update_fn,
        cache_name="test_cache",
    )


class TestDjangoKeyPrefix(BaseTest):
    """Test _django_key_prefix property extraction."""

    def test_extracts_prefix_from_cache_client(self):
        """Test that _django_key_prefix extracts prefix and version from cache client."""
        config = create_test_config()

        # Mock cache client with key_prefix and version
        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = "posthog"
        mock_cache_client.version = 1

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            prefix = config._django_key_prefix

        assert prefix == "posthog:1:"

    def test_returns_empty_string_when_no_prefix(self):
        """Test that _django_key_prefix returns empty string when key_prefix is empty."""
        config = create_test_config()

        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = ""
        mock_cache_client.version = 1

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            prefix = config._django_key_prefix

        assert prefix == ""

    def test_handles_missing_key_prefix_attribute(self):
        """Test graceful handling when cache client lacks key_prefix attribute."""
        config = create_test_config()

        mock_cache_client = MagicMock(spec=[])  # No attributes
        del mock_cache_client.key_prefix  # Ensure it's not present

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            prefix = config._django_key_prefix

        assert prefix == ""

    def test_handles_missing_version_attribute(self):
        """Test that missing version defaults to 1."""
        config = create_test_config()

        mock_cache_client = MagicMock(spec=["key_prefix"])
        mock_cache_client.key_prefix = "posthog"
        # version is missing, should default to 1

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            prefix = config._django_key_prefix

        assert prefix == "posthog:1:"

    def test_handles_custom_version(self):
        """Test that custom version is used in prefix."""
        config = create_test_config()

        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = "posthog"
        mock_cache_client.version = 2

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            prefix = config._django_key_prefix

        assert prefix == "posthog:2:"


class TestRedisPatterns(BaseTest):
    """Test Redis pattern generation with Django prefix."""

    def test_redis_pattern_includes_django_prefix(self):
        """Test that redis_pattern includes the Django key prefix."""
        config = create_test_config(namespace="feature_flags", value="flags.json")

        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = "posthog"
        mock_cache_client.version = 1

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            pattern = config.redis_pattern

        assert pattern == "posthog:1:cache/teams/*/feature_flags/*"

    def test_redis_stats_pattern_includes_django_prefix(self):
        """Test that redis_stats_pattern includes the Django key prefix."""
        config = create_test_config(namespace="feature_flags", value="flags.json")

        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = "posthog"
        mock_cache_client.version = 1

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            pattern = config.redis_stats_pattern

        assert pattern == "posthog:1:cache/teams/*/feature_flags/flags.json"

    def test_redis_pattern_for_token_based_cache(self):
        """Test that token-based caches use team_tokens prefix."""
        config = create_test_config(namespace="feature_flags", value="flags.json", token_based=True)

        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = "posthog"
        mock_cache_client.version = 1

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            pattern = config.redis_pattern

        assert pattern == "posthog:1:cache/team_tokens/*/feature_flags/*"

    def test_redis_pattern_without_django_prefix(self):
        """Test pattern generation when there's no Django prefix."""
        config = create_test_config(namespace="feature_flags", value="flags.json")

        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = ""
        mock_cache_client.version = 1

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            pattern = config.redis_pattern

        assert pattern == "cache/teams/*/feature_flags/*"


class TestRedisUrlRouting(BaseTest):
    """Test that cache operations use the correct Redis instance."""

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_get_cache_stats_uses_config_redis_url(self, mock_get_client):
        """Test that get_cache_stats uses the Redis URL from config."""
        config = create_test_config()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = iter([])
        mock_redis.zcard.return_value = 0

        # Mock the hypercache's redis_url to simulate a dedicated Redis
        with patch.object(config.hypercache, "redis_url", "redis://dedicated:6379/1"):
            with patch("posthog.models.team.team.Team.objects.count", return_value=10):
                get_cache_stats(config)

        mock_get_client.assert_called_once_with("redis://dedicated:6379/1")

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_get_cache_stats_uses_default_redis_url(self, mock_get_client):
        """Test that get_cache_stats uses the default Redis URL from settings."""
        config = create_test_config()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = iter([])
        mock_redis.zcard.return_value = 0

        with patch("posthog.models.team.team.Team.objects.count", return_value=10):
            get_cache_stats(config)

        # Should be called with whatever redis_url the hypercache has (settings.REDIS_URL)
        mock_get_client.assert_called_once()
        # The default hypercache uses settings.REDIS_URL
        call_args = mock_get_client.call_args[0]
        assert call_args[0] is not None  # Should have a URL from settings

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_invalidate_all_caches_uses_config_redis_url(self, mock_get_client):
        """Test that invalidate_all_caches uses the Redis URL from config.

        Regression test: Previously this function used get_client() without
        the redis_url, causing it to scan the wrong Redis instance.
        """
        config = create_test_config()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = iter([])

        # Mock the hypercache's redis_url to simulate a dedicated Redis
        with patch.object(config.hypercache, "redis_url", "redis://dedicated:6379/1"):
            invalidate_all_caches(config)

        mock_get_client.assert_called_once_with("redis://dedicated:6379/1")

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_invalidate_all_caches_uses_default_redis_url(self, mock_get_client):
        """Test that invalidate_all_caches uses the default Redis URL from settings."""
        config = create_test_config()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = iter([])

        invalidate_all_caches(config)

        # Should be called with whatever redis_url the hypercache has
        mock_get_client.assert_called_once()
        call_args = mock_get_client.call_args[0]
        assert call_args[0] is not None  # Should have a URL from settings


class TestInvalidateAllCaches(BaseTest):
    """Test invalidate_all_caches functionality."""

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_deletes_matching_keys(self, mock_get_client):
        """Test that invalidate_all_caches deletes all keys matching the pattern."""
        config = create_test_config()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = iter([b"key1", b"key2", b"key3"])

        deleted_count = invalidate_all_caches(config)

        assert deleted_count == 3
        # 3 cache keys + 1 expiry sorted set = 4 total deletes
        assert mock_redis.delete.call_count == 4

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_clears_expiry_sorted_set(self, mock_get_client):
        """Test that invalidate_all_caches also clears the expiry tracking set."""
        config = create_test_config()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = iter([])

        invalidate_all_caches(config)

        # Should delete the expiry sorted set
        mock_redis.delete.assert_called_with(config.hypercache.expiry_sorted_set_key)

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_returns_zero_on_error(self, mock_get_client):
        """Test that invalidate_all_caches returns 0 on error."""
        config = create_test_config()

        mock_get_client.side_effect = Exception("Redis connection failed")

        deleted_count = invalidate_all_caches(config)

        assert deleted_count == 0

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_uses_correct_pattern_with_django_prefix(self, mock_get_client):
        """Test that scan uses the pattern with Django prefix."""
        config = create_test_config(namespace="feature_flags", value="flags.json")

        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = "posthog"
        mock_cache_client.version = 1

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = iter([])

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            invalidate_all_caches(config)

        # Verify scan was called with the correct pattern
        mock_redis.scan_iter.assert_called_once()
        call_kwargs = mock_redis.scan_iter.call_args[1]
        assert call_kwargs["match"] == "posthog:1:cache/teams/*/feature_flags/*"


class TestGetCacheStats(BaseTest):
    """Test get_cache_stats functionality."""

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_returns_stats_with_coverage(self, mock_get_client):
        """Test that get_cache_stats returns correct coverage statistics."""
        config = create_test_config()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Mock scan returning 5 keys
        mock_redis.scan_iter.side_effect = [
            iter([b"key1", b"key2", b"key3", b"key4", b"key5"]),  # TTL scan
            iter([b"key1", b"key2"]),  # Memory sample
        ]

        mock_pipeline = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_pipeline.execute.side_effect = [
            [3600, 86400, 604800, 700000, -1],  # TTL results
            [1024, 2048],  # Memory results
        ]
        mock_redis.zcard.return_value = 5

        with patch("posthog.models.team.team.Team.objects.count", return_value=10):
            stats = get_cache_stats(config)

        assert stats["total_cached"] == 5
        assert stats["total_teams"] == 10
        assert stats["cache_coverage_percent"] == 50.0
        assert stats["expiry_tracked"] == 5

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_ttl_distribution_buckets(self, mock_get_client):
        """Test that TTL distribution is correctly bucketed."""
        config = create_test_config()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        mock_redis.scan_iter.side_effect = [
            iter([b"k1", b"k2", b"k3", b"k4", b"k5"]),
            iter([]),  # No memory sampling
        ]

        mock_pipeline = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [
            -1,  # expired
            1800,  # expires in 1h (< 3600)
            43200,  # expires in 24h (< 86400)
            302400,  # expires in 7d (< 604800)
            700000,  # expires later (> 604800)
        ]
        mock_redis.zcard.return_value = 5

        with patch("posthog.models.team.team.Team.objects.count", return_value=10):
            stats = get_cache_stats(config)

        assert stats["ttl_distribution"]["expired"] == 1
        assert stats["ttl_distribution"]["expires_1h"] == 1
        assert stats["ttl_distribution"]["expires_24h"] == 1
        assert stats["ttl_distribution"]["expires_7d"] == 1
        assert stats["ttl_distribution"]["expires_later"] == 1

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_returns_error_on_exception(self, mock_get_client):
        """Test that get_cache_stats returns error dict on exception."""
        config = create_test_config()

        mock_get_client.side_effect = Exception("Redis connection failed")

        stats = get_cache_stats(config)

        assert "error" in stats
        assert stats["namespace"] == "test_namespace"

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_uses_correct_pattern_with_django_prefix(self, mock_get_client):
        """Test that scan uses the stats pattern with Django prefix."""
        config = create_test_config(namespace="feature_flags", value="flags.json")

        mock_cache_client = MagicMock()
        mock_cache_client.key_prefix = "posthog"
        mock_cache_client.version = 1

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = iter([])
        mock_redis.zcard.return_value = 0

        with patch.object(config.hypercache, "cache_client", mock_cache_client):
            with patch("posthog.models.team.team.Team.objects.count", return_value=10):
                get_cache_stats(config)

        # First scan call should use the stats pattern
        first_call = mock_redis.scan_iter.call_args_list[0]
        assert first_call[1]["match"] == "posthog:1:cache/teams/*/feature_flags/flags.json"


class TestPushHypercacheStatsMetrics(BaseTest):
    """Test push_hypercache_stats_metrics functionality."""

    @patch("posthog.storage.hypercache_manager.pushed_metrics_registry")
    def test_pushes_metrics_to_pushgateway(self, mock_registry_cm):
        """Test that metrics are pushed to Pushgateway when configured."""
        mock_registry = MagicMock()
        mock_registry_cm.return_value.__enter__ = MagicMock(return_value=mock_registry)
        mock_registry_cm.return_value.__exit__ = MagicMock(return_value=False)

        with self.settings(PROM_PUSHGATEWAY_ADDRESS="http://pushgateway:9091"):
            push_hypercache_stats_metrics(
                namespace="feature_flags",
                coverage_percent=85.5,
                entries_total=1000,
                expiry_tracked_total=950,
                size_bytes=1024000,
            )

        mock_registry_cm.assert_called_once_with("hypercache_stats_feature_flags")

    @patch("posthog.storage.hypercache_manager.pushed_metrics_registry")
    def test_skips_push_when_no_pushgateway_address(self, mock_registry_cm):
        """Test that no push happens when PROM_PUSHGATEWAY_ADDRESS is not set."""
        with self.settings(PROM_PUSHGATEWAY_ADDRESS=None):
            push_hypercache_stats_metrics(
                namespace="feature_flags",
                coverage_percent=85.5,
                entries_total=1000,
                expiry_tracked_total=950,
                size_bytes=1024000,
            )

        mock_registry_cm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.pushed_metrics_registry")
    def test_skips_size_gauge_when_size_bytes_is_none(self, mock_registry_cm):
        """Test that size gauge is not created when size_bytes is None."""
        mock_registry = MagicMock()
        mock_registry_cm.return_value.__enter__ = MagicMock(return_value=mock_registry)
        mock_registry_cm.return_value.__exit__ = MagicMock(return_value=False)

        with self.settings(PROM_PUSHGATEWAY_ADDRESS="http://pushgateway:9091"):
            push_hypercache_stats_metrics(
                namespace="team_metadata",
                coverage_percent=90.0,
                entries_total=500,
                expiry_tracked_total=500,
                size_bytes=None,
            )

        mock_registry_cm.assert_called_once_with("hypercache_stats_team_metadata")

    @patch("posthog.storage.hypercache_manager.pushed_metrics_registry")
    @patch("posthog.storage.hypercache_manager.logger")
    def test_logs_warning_on_push_failure(self, mock_logger, mock_registry_cm):
        """Test that a warning is logged when push fails."""
        mock_registry_cm.return_value.__enter__ = MagicMock(side_effect=Exception("Connection failed"))
        mock_registry_cm.return_value.__exit__ = MagicMock(return_value=False)

        with self.settings(PROM_PUSHGATEWAY_ADDRESS="http://pushgateway:9091"):
            push_hypercache_stats_metrics(
                namespace="feature_flags",
                coverage_percent=85.5,
                entries_total=1000,
                expiry_tracked_total=950,
                size_bytes=1024000,
            )

        mock_logger.warning.assert_called_once()
        assert "Failed to push hypercache stats" in str(mock_logger.warning.call_args)


class TestConfigValidation(BaseTest):
    """Test HyperCacheManagementConfig validation."""

    def test_both_optimization_fields_none_is_valid(self):
        """Config with both optimization fields None is valid."""
        # Should not raise
        config = create_test_config()
        assert config.get_team_ids_needing_full_verification_fn is None
        assert config.empty_cache_value is None

    def test_both_optimization_fields_set_is_valid(self):
        """Config with both optimization fields set is valid."""
        hypercache = create_test_hypercache()

        def update_fn(team, ttl=None):
            return True

        def get_team_ids():
            return {1, 2, 3}

        # Should not raise
        config = HyperCacheManagementConfig(
            hypercache=hypercache,
            update_fn=update_fn,
            cache_name="test_cache",
            get_team_ids_needing_full_verification_fn=get_team_ids,
            empty_cache_value={"flags": []},
        )
        assert config.get_team_ids_needing_full_verification_fn is not None
        assert config.empty_cache_value is not None

    def test_only_team_ids_fn_set_raises_error(self):
        """Config with only get_team_ids_needing_full_verification_fn raises ValueError."""
        hypercache = create_test_hypercache()

        def update_fn(team, ttl=None):
            return True

        def get_team_ids():
            return {1, 2, 3}

        with self.assertRaises(ValueError) as context:
            HyperCacheManagementConfig(
                hypercache=hypercache,
                update_fn=update_fn,
                cache_name="test_cache",
                get_team_ids_needing_full_verification_fn=get_team_ids,
                empty_cache_value=None,  # Missing!
            )

        assert "both get_team_ids_needing_full_verification_fn and empty_cache_value" in str(context.exception)

    def test_only_empty_cache_value_set_raises_error(self):
        """Config with only empty_cache_value raises ValueError."""
        hypercache = create_test_hypercache()

        def update_fn(team, ttl=None):
            return True

        with self.assertRaises(ValueError) as context:
            HyperCacheManagementConfig(
                hypercache=hypercache,
                update_fn=update_fn,
                cache_name="test_cache",
                get_team_ids_needing_full_verification_fn=None,  # Missing!
                empty_cache_value={"flags": []},
            )

        assert "both get_team_ids_needing_full_verification_fn and empty_cache_value" in str(context.exception)
