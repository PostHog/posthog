from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.caching.redis_cluster_connection_factory import (
    QUERY_CACHE_ALIAS,
    RedisClusterConnectionFactory,
    prewarm_query_cache_cluster,
    prewarm_query_cache_cluster_in_background,
)


class TestRedisClusterConnectionFactory(TestCase):
    def setUp(self) -> None:
        super().setUp()
        RedisClusterConnectionFactory._cluster_clients.clear()

    def tearDown(self) -> None:
        RedisClusterConnectionFactory._cluster_clients.clear()
        super().tearDown()

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
        from_url.assert_called_once_with("redis://node-a:6379", socket_keepalive=True)

    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_connect_constructs_one_client_per_distinct_url(self, from_url: MagicMock) -> None:
        factory = self._factory()
        from_url.side_effect = lambda url, **kwargs: MagicMock(name=url)

        factory.connect("redis://node-a:6379")
        factory.connect("redis://node-b:6379")
        factory.connect("redis://node-a:6379")

        assert from_url.call_count == 2

    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_discovered_client_is_shared_across_factory_instances(self, from_url: MagicMock) -> None:
        sentinel = MagicMock()
        from_url.return_value = sentinel

        # Django builds a fresh factory per request/thread; discovery must still
        # happen only once because the cache is process-global, not per-instance.
        first = self._factory().connect("redis://node-a:6379")
        second = self._factory().connect("redis://node-a:6379")

        assert first is second is sentinel
        from_url.assert_called_once_with("redis://node-a:6379", socket_keepalive=True)

    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_disconnect_evicts_client_so_next_connect_rediscovers(self, from_url: MagicMock) -> None:
        from_url.side_effect = lambda url, **kwargs: MagicMock(name=url)
        factory = self._factory()

        first = factory.connect("redis://node-a:6379")
        factory.disconnect(first)
        second = factory.connect("redis://node-a:6379")

        first.close.assert_called_once_with()
        assert second is not first
        assert from_url.call_count == 2


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


class TestPrewarmInBackground(TestCase):
    def test_runs_prewarm_on_a_completed_daemon_thread(self) -> None:
        with patch("posthog.caching.redis_cluster_connection_factory.settings") as mock_settings:
            mock_settings.CACHES = {QUERY_CACHE_ALIAS: {}}
            with patch("posthog.caching.redis_cluster_connection_factory.caches") as mock_caches:
                thread = prewarm_query_cache_cluster_in_background()
                thread.join(timeout=5)
                assert thread.daemon is True
                assert not thread.is_alive()
                mock_caches[QUERY_CACHE_ALIAS].get.assert_called_once_with("__prewarm__")

    def test_thread_never_raises_when_prewarm_fails(self) -> None:
        with patch("posthog.caching.redis_cluster_connection_factory.settings") as mock_settings:
            mock_settings.CACHES = {QUERY_CACHE_ALIAS: {}}
            with patch("posthog.caching.redis_cluster_connection_factory.caches") as mock_caches:
                mock_caches[QUERY_CACHE_ALIAS].get.side_effect = ConnectionError("cluster down")
                with patch("posthog.caching.redis_cluster_connection_factory.logger"):
                    thread = prewarm_query_cache_cluster_in_background()
                    thread.join(timeout=5)
                    assert not thread.is_alive()
