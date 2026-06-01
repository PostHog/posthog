from unittest.mock import MagicMock, patch

from django.test import TestCase

from prometheus_client import REGISTRY

from posthog.caching.redis_cluster_connection_factory import (
    QUERY_CACHE_ALIAS,
    RedisClusterConnectionFactory,
    prewarm_query_cache_cluster,
)


def _discovery_count() -> float:
    return REGISTRY.get_sample_value("posthog_redis_cluster_discovery_duration_seconds_count") or 0.0


class TestRedisClusterConnectionFactory(TestCase):
    def _factory(self) -> RedisClusterConnectionFactory:
        return RedisClusterConnectionFactory(options={})

    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_connect_constructs_cluster_client_once_per_url(self, from_url: MagicMock) -> None:
        factory = self._factory()
        sentinel = MagicMock()
        from_url.return_value = sentinel

        first = factory.connect("redis://node-a:6379")
        second = factory.connect("redis://node-a:6379")

        assert first is sentinel
        assert second is sentinel
        from_url.assert_called_once_with("redis://node-a:6379")

    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_connect_constructs_one_client_per_distinct_url(self, from_url: MagicMock) -> None:
        factory = self._factory()
        from_url.side_effect = lambda url: MagicMock(name=url)

        factory.connect("redis://node-a:6379")
        factory.connect("redis://node-b:6379")
        factory.connect("redis://node-a:6379")

        assert from_url.call_count == 2

    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_discovery_metric_records_only_on_construction(self, from_url: MagicMock) -> None:
        factory = self._factory()
        from_url.return_value = MagicMock()

        before = _discovery_count()
        factory.connect("redis://counter-test:6379")
        factory.connect("redis://counter-test:6379")

        assert _discovery_count() == before + 1


class TestPrewarmQueryCacheCluster(TestCase):
    def test_no_op_when_alias_not_configured(self) -> None:
        with patch("posthog.caching.redis_cluster_connection_factory.settings") as mock_settings:
            mock_settings.CACHES = {}
            with patch("posthog.caching.redis_cluster_connection_factory.caches") as mock_caches:
                prewarm_query_cache_cluster()
                mock_caches.__getitem__.assert_not_called()

    def test_issues_trivial_read_when_alias_configured(self) -> None:
        with patch("posthog.caching.redis_cluster_connection_factory.settings") as mock_settings:
            mock_settings.CACHES = {QUERY_CACHE_ALIAS: {}}
            with patch("posthog.caching.redis_cluster_connection_factory.caches") as mock_caches:
                prewarm_query_cache_cluster()
                mock_caches[QUERY_CACHE_ALIAS].get.assert_called_once_with("__prewarm__")

    def test_swallows_and_logs_connection_errors(self) -> None:
        with patch("posthog.caching.redis_cluster_connection_factory.settings") as mock_settings:
            mock_settings.CACHES = {QUERY_CACHE_ALIAS: {}}
            with patch("posthog.caching.redis_cluster_connection_factory.caches") as mock_caches:
                mock_caches[QUERY_CACHE_ALIAS].get.side_effect = ConnectionError("cluster down")
                with patch("posthog.caching.redis_cluster_connection_factory.logger") as mock_logger:
                    prewarm_query_cache_cluster()
                    mock_logger.warning.assert_called_once()
