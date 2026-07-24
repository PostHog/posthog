from datetime import UTC, datetime, timedelta

from freezegun import freeze_time

from django.core.cache import caches
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS
from posthog.query_cache.failures import (
    BASE_BACKOFF,
    MAX_BACKOFF,
    OPEN_THRESHOLD,
    SCOPE_ASYNC,
    SCOPE_SYNC,
    QueryFailureCache,
)


class TestQueryFailureCache(SimpleTestCase):
    def setUp(self):
        super().setUp()
        caches[QUERY_CACHE_ALIAS].clear()

    @parameterized.expand(
        [
            ("sync_timeout_spares_async", "timeout", SCOPE_SYNC, False),
            ("async_timeout_suppresses_async", "timeout", SCOPE_ASYNC, True),
            ("sync_too_slow_spares_async", "too_slow", SCOPE_SYNC, False),
            ("memory_suppresses_regardless", "memory_limit", SCOPE_SYNC, True),
            ("query_size_suppresses_regardless", "query_size", SCOPE_SYNC, True),
        ]
    )
    def test_suppresses_async_dispatch_by_kind_and_scope(self, _name, kind, scope, expected):
        record = QueryFailureCache("cache_key_scope").record_failure(kind, "failed", scope=scope)
        assert record is not None
        assert record.suppresses_async_dispatch is expected

    def test_async_scope_is_sticky_across_later_sync_failures(self):
        failure_cache = QueryFailureCache("cache_key_sticky")
        failure_cache.record_failure("timeout", "failed", scope=SCOPE_ASYNC)
        record = failure_cache.record_failure("timeout", "failed", scope=SCOPE_SYNC)
        assert record is not None
        assert record.scope == SCOPE_ASYNC
        assert record.suppresses_async_dispatch

    def test_unknown_kind_raises_instead_of_failing_open(self):
        with self.assertRaises(ValueError):
            QueryFailureCache("cache_key_bad").record_failure("not_a_kind", "failed")  # type: ignore[arg-type]

    def test_unknown_kind_in_cache_fails_open(self):
        caches[QUERY_CACHE_ALIAS].set(
            "query_failure:cache_key_future",
            {
                "kind": "kind_from_a_newer_release",
                "detail": "x",
                "consecutive_failures": 99,
                "last_failed_at": datetime.now(UTC).isoformat(),
                "open_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "scope": SCOPE_SYNC,
            },
            300,
        )
        assert QueryFailureCache("cache_key_future").get_open() is None

    def test_load_dependent_breaker_opens_after_threshold_and_backs_off_exponentially(self):
        failure_cache = QueryFailureCache("cache_key_1")
        with freeze_time("2026-01-01T00:00:00Z") as frozen:
            for _ in range(OPEN_THRESHOLD["timeout"] - 1):
                failure_cache.record_failure("timeout", "failed")
                assert failure_cache.get_open() is None

            record = failure_cache.record_failure("timeout", "failed")
            assert record is not None
            assert record.open_until == datetime.now(UTC) + BASE_BACKOFF
            assert failure_cache.get_open() is not None

            frozen.tick(BASE_BACKOFF + timedelta(seconds=1))
            assert failure_cache.get_open() is None
            record = failure_cache.record_failure("timeout", "failed")
            assert record is not None
            assert record.open_until == datetime.now(UTC) + BASE_BACKOFF * 2

    @parameterized.expand([("memory_limit",), ("query_size",)])
    def test_deterministic_kinds_open_on_first_failure(self, kind):
        failure_cache = QueryFailureCache(f"cache_key_instant_{kind}")
        with freeze_time("2026-01-01T00:00:00Z"):
            record = failure_cache.record_failure(kind, "failed")
            assert record is not None
            assert record.consecutive_failures == 1
            assert record.open_until == datetime.now(UTC) + BASE_BACKOFF
            assert failure_cache.get_open() is not None

            record = failure_cache.record_failure(kind, "failed")
            assert record is not None
            assert record.open_until == datetime.now(UTC) + BASE_BACKOFF * 2

    def test_backoff_is_capped_and_survives_high_failure_counts(self):
        # 50 failures is past the point where uncapped backoff math overflows timedelta.
        failure_cache = QueryFailureCache("cache_key_2")
        with freeze_time("2026-01-01T00:00:00Z"):
            record = None
            for _ in range(50):
                record = failure_cache.record_failure("timeout", "failed")
            assert record is not None
            assert record.consecutive_failures == 50
            assert record.open_until == datetime.now(UTC) + MAX_BACKOFF["timeout"]

    def test_kind_change_resets_the_consecutive_count(self):
        failure_cache = QueryFailureCache("cache_key_kind_change")
        failure_cache.record_failure("timeout", "failed")
        failure_cache.record_failure("timeout", "failed")
        record = failure_cache.record_failure("too_slow", "failed")
        assert record is not None
        assert record.consecutive_failures == 1

    def test_clear_closes_breaker_and_resets_count(self):
        failure_cache = QueryFailureCache("cache_key_3")
        with freeze_time("2026-01-01T00:00:00Z"):
            for _ in range(3):
                failure_cache.record_failure("memory_limit", "failed")
            assert failure_cache.get_open() is not None

            failure_cache.clear()
            assert failure_cache.get_open() is None
            record = failure_cache.record_failure("memory_limit", "failed")
            assert record is not None
            assert record.consecutive_failures == 1

    def test_detail_is_capped(self):
        record = QueryFailureCache("cache_key_detail").record_failure("timeout", "x" * 5000)
        assert record is not None
        assert len(record.detail) == 1000
