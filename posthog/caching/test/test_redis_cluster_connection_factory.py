import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from parameterized import parameterized

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
        RedisClusterConnectionFactory._owner_pid = None

    def tearDown(self) -> None:
        RedisClusterConnectionFactory._cluster_clients.clear()
        RedisClusterConnectionFactory._owner_pid = None
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
    def test_concurrent_connect_discovers_once_and_returns_one_shared_client(self, from_url: MagicMock) -> None:
        # A thundering herd of request threads must not each run discovery: the
        # double-checked lock means exactly one construction even when every
        # thread races into connect() at the same instant.
        sentinel = MagicMock()
        from_url.return_value = sentinel

        thread_count = 16
        start = threading.Barrier(thread_count)
        results: list[object] = []
        results_lock = threading.Lock()

        def worker() -> None:
            factory = self._factory()  # a fresh per-thread factory, as Django builds per request
            start.wait()
            client = factory.connect("redis://node-a:6379")
            with results_lock:
                results.append(client)

        with ThreadPoolExecutor(max_workers=thread_count) as pool:
            for future in [pool.submit(worker) for _ in range(thread_count)]:
                future.result()

        assert from_url.call_count == 1
        assert results == [sentinel] * thread_count

    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_cache_hit_never_acquires_the_global_lock(self, from_url: MagicMock) -> None:
        # The lock guards construction only. If it leaked onto the cache-hit path
        # it would serialize every query-cache access process-wide and block the
        # server under load, so assert the warm path takes it zero times.
        from_url.return_value = MagicMock()

        class CountingLock:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self.enter_count = 0

            def __enter__(self) -> None:
                self.enter_count += 1
                self._lock.acquire()

            def __exit__(self, *args: object) -> None:
                self._lock.release()

        counting_lock = CountingLock()
        with patch.object(RedisClusterConnectionFactory, "_lock", counting_lock):
            factory = self._factory()
            factory.connect("redis://node-a:6379")  # cold: one construction → one acquire
            enters_after_warmup = counting_lock.enter_count
            for _ in range(50):
                factory.connect("redis://node-a:6379")  # warm: must not touch the lock

        assert enters_after_warmup == 1
        assert counting_lock.enter_count == 1

    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_shared_state_lives_on_the_class_not_the_instance(self, from_url: MagicMock) -> None:
        # The fork guard only works if _owner_pid and the client cache are
        # process-global. If either were ever written through `self` it would
        # shadow onto the instance, every fresh per-request factory would look
        # unforked, and discovery would run per request again. Pin them to the class.
        from_url.return_value = MagicMock()
        factory = self._factory()

        factory.connect("redis://node-a:6379")

        assert RedisClusterConnectionFactory._owner_pid == os.getpid()
        assert "_owner_pid" not in factory.__dict__
        assert "_cluster_clients" not in factory.__dict__

    @patch("posthog.caching.redis_cluster_connection_factory.os.getpid")
    @patch("posthog.caching.redis_cluster_connection_factory.RedisCluster.from_url")
    def test_connect_rediscovers_after_a_fork(self, from_url: MagicMock, getpid: MagicMock) -> None:
        # A client discovered pre-fork holds the parent's sockets; once getpid()
        # changes (the worker is a forked child) connect() must drop the inherited
        # cache and rediscover so workers never share file descriptors.
        from_url.side_effect = lambda url, **kwargs: MagicMock(name=url)
        getpid.return_value = 1000
        parent_client = self._factory().connect("redis://node-a:6379")

        getpid.return_value = 2000  # forked worker
        child_client = self._factory().connect("redis://node-a:6379")

        assert child_client is not parent_client
        assert from_url.call_count == 2

    @parameterized.expand(
        [
            ("alias_option", {"CLOSE_CONNECTION": True}, {}),
            ("global_setting", {}, {"DJANGO_REDIS_CLOSE_CONNECTION": True}),
        ]
    )
    def test_init_rejects_close_connection(self, _name: str, options: dict, settings_overrides: dict) -> None:
        with self.settings(**settings_overrides), pytest.raises(ImproperlyConfigured):
            RedisClusterConnectionFactory(options=options)


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
