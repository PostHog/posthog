from unittest import mock

from django.test import SimpleTestCase, override_settings

from posthog.db_circuit_breaker import ProductDBCircuitBreaker, _get_redis
from posthog.redis import get_client

ALIAS = "visual_review_db_reader"

BREAKER_SETTINGS = {
    "PRODUCT_DB_CIRCUIT_BREAKER_ENABLED": True,
    "PRODUCT_DB_CIRCUIT_BREAKER_FAILURE_THRESHOLD": 3,
    "PRODUCT_DB_CIRCUIT_BREAKER_COOLDOWN_SECONDS": 30,
    "PRODUCT_DB_CIRCUIT_BREAKER_PROBE_TIMEOUT_SECONDS": 5,
    "PRODUCT_DB_CIRCUIT_BREAKER_WINDOW_SECONDS": 30,
}


@override_settings(**BREAKER_SETTINGS)
class TestProductDBCircuitBreaker(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        _get_redis.cache_clear()
        get_client().flushdb()
        self.clock = {"now": 1000.0}
        self.now_patch = mock.patch("posthog.db_circuit_breaker._now", side_effect=lambda: self.clock["now"])
        self.now_patch.start()
        self.addCleanup(self.now_patch.stop)
        self.addCleanup(_get_redis.cache_clear)

    def _open_breaker(self, breaker: ProductDBCircuitBreaker) -> None:
        for _ in range(BREAKER_SETTINGS["PRODUCT_DB_CIRCUIT_BREAKER_FAILURE_THRESHOLD"]):
            breaker.record_failure(ALIAS, was_probe=False)

    def test_closed_breaker_allows_without_probe(self) -> None:
        decision = ProductDBCircuitBreaker().before_connect(ALIAS)
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.is_probe)

    def test_failures_below_threshold_stay_closed(self) -> None:
        breaker = ProductDBCircuitBreaker()
        breaker.record_failure(ALIAS, was_probe=False)
        breaker.record_failure(ALIAS, was_probe=False)

        self.assertTrue(ProductDBCircuitBreaker().before_connect(ALIAS).allowed)

    def test_opens_after_threshold_failures(self) -> None:
        breaker = ProductDBCircuitBreaker()
        self._open_breaker(breaker)

        # A fresh breaker (other worker) sees the open state via shared Redis.
        self.assertFalse(ProductDBCircuitBreaker().before_connect(ALIAS).allowed)

    def test_denied_worker_caches_real_redis_deadline(self) -> None:
        # Breaker opens at now=1000, so Redis holds open_until=1030.
        self._open_breaker(ProductDBCircuitBreaker())
        self.clock["now"] += 25  # 1025, still within cooldown

        other_worker = ProductDBCircuitBreaker()
        self.assertFalse(other_worker.before_connect(ALIAS).allowed)
        # Caches the real Redis deadline (1030), not a fresh now+cooldown (1055).
        self.assertEqual(other_worker._local_open_until[ALIAS], 1030.0)

    def test_open_marker_outlives_cooldown(self) -> None:
        # The open marker must persist far longer than the cooldown so an idle,
        # still-down product forces a probe (not a connect stampede) when traffic
        # resumes. TTL uses fakeredis wall-clock, so assert right after opening.
        self._open_breaker(ProductDBCircuitBreaker())

        _, open_until_key, _ = ProductDBCircuitBreaker()._keys(ALIAS)
        ttl = get_client().ttl(open_until_key)
        self.assertGreater(ttl, BREAKER_SETTINGS["PRODUCT_DB_CIRCUIT_BREAKER_COOLDOWN_SECONDS"])

    def test_other_apps_unaffected_by_open_breaker(self) -> None:
        self._open_breaker(ProductDBCircuitBreaker())

        self.assertTrue(ProductDBCircuitBreaker().before_connect("warehouse_sources_queue_db_reader").allowed)

    def test_half_open_grants_single_probe(self) -> None:
        self._open_breaker(ProductDBCircuitBreaker())
        self.clock["now"] += 31  # cooldown elapsed

        first = ProductDBCircuitBreaker().before_connect(ALIAS)
        second = ProductDBCircuitBreaker().before_connect(ALIAS)

        self.assertTrue(first.allowed)
        self.assertTrue(first.is_probe)
        # Lease is held by the first probe — concurrent workers keep failing fast.
        self.assertFalse(second.allowed)

    def test_successful_probe_closes_breaker(self) -> None:
        self._open_breaker(ProductDBCircuitBreaker())
        self.clock["now"] += 31

        prober = ProductDBCircuitBreaker()
        probe = prober.before_connect(ALIAS)
        self.assertTrue(probe.is_probe)
        prober.record_success(ALIAS, was_probe=True)

        self.assertTrue(ProductDBCircuitBreaker().before_connect(ALIAS).allowed)

    def test_failed_probe_reopens_breaker(self) -> None:
        self._open_breaker(ProductDBCircuitBreaker())
        self.clock["now"] += 31

        prober = ProductDBCircuitBreaker()
        probe = prober.before_connect(ALIAS)
        self.assertTrue(probe.is_probe)
        prober.record_failure(ALIAS, was_probe=True)

        # Still open right after the failed probe; cooldown restarts.
        self.assertFalse(ProductDBCircuitBreaker().before_connect(ALIAS).allowed)
        self.clock["now"] += 31
        self.assertTrue(ProductDBCircuitBreaker().before_connect(ALIAS).is_probe)

    def test_local_cache_short_circuits_redis_while_open(self) -> None:
        breaker = ProductDBCircuitBreaker()
        self._open_breaker(breaker)

        # The breaker that tripped caches the open deadline and never hits Redis again.
        with mock.patch("posthog.db_circuit_breaker._get_redis") as redis_mock:
            self.assertFalse(breaker.before_connect(ALIAS).allowed)
            redis_mock.assert_not_called()

    @override_settings(PRODUCT_DB_CIRCUIT_BREAKER_ENABLED=False)
    def test_disabled_breaker_always_allows(self) -> None:
        breaker = ProductDBCircuitBreaker()
        self._open_breaker(breaker)

        self.assertTrue(breaker.before_connect(ALIAS).allowed)

    def test_fails_safe_open_when_redis_unavailable(self) -> None:
        with mock.patch("posthog.db_circuit_breaker._get_redis", return_value=None):
            self.assertTrue(ProductDBCircuitBreaker().before_connect(ALIAS).allowed)

    def test_redis_error_fails_safe_to_closed(self) -> None:
        breaker = ProductDBCircuitBreaker()
        breaker._allow_script = mock.Mock(side_effect=Exception("redis down"))
        self.assertTrue(breaker.before_connect(ALIAS).allowed)
