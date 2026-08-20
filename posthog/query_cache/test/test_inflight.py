from unittest.mock import patch

from django.test import SimpleTestCase

import orjson

from posthog.query_cache import storage
from posthog.query_cache.inflight import (
    WaitOutcome,
    _claim_redis_key,
    _refresh_active_claims,
    acquire_claim,
    release_claim,
    wait_for_cached_result,
)
from posthog.query_cache.results import EntryFreshness


class TestInflightClaims(SimpleTestCase):
    CACHE_KEY = "inflight_test_key"

    def setUp(self) -> None:
        super().setUp()
        self.redis = storage.query_cache_raw_client()
        self._cleanup()

    def tearDown(self) -> None:
        self._cleanup()
        super().tearDown()

    def _cleanup(self) -> None:
        self.redis.delete(_claim_redis_key(self.CACHE_KEY), storage.entry_redis_key(self.CACHE_KEY))

    def _store_entry(self, last_refresh: str) -> None:
        value = orjson.dumps({"results": [1], "is_cached": False, "last_refresh": last_refresh})
        self.redis.set(storage.entry_redis_key(self.CACHE_KEY), value)

    def test_claim_is_exclusive_until_released(self):
        claim = acquire_claim(self.CACHE_KEY)
        assert claim is not None
        assert acquire_claim(self.CACHE_KEY) is None

        release_claim(claim)
        second = acquire_claim(self.CACHE_KEY)
        assert second is not None
        release_claim(second)

    def test_release_ignores_a_claim_it_no_longer_owns(self):
        stale = acquire_claim(self.CACHE_KEY)
        assert stale is not None
        # The claim expires (dead-process TTL) and a waiter takes over.
        self.redis.delete(_claim_redis_key(self.CACHE_KEY))
        successor = acquire_claim(self.CACHE_KEY)
        assert successor is not None

        release_claim(stale)

        assert self.redis.get(_claim_redis_key(self.CACHE_KEY)) == successor.run_id.encode()
        release_claim(successor)

    def test_refresh_extends_owned_and_drops_lost_claims(self):
        claim = acquire_claim(self.CACHE_KEY)
        assert claim is not None
        self.redis.expire(_claim_redis_key(self.CACHE_KEY), 5)

        _refresh_active_claims()
        assert self.redis.ttl(_claim_redis_key(self.CACHE_KEY)) > 5

        self.redis.set(_claim_redis_key(self.CACHE_KEY), "another-run", ex=5)
        _refresh_active_claims()
        assert self.redis.ttl(_claim_redis_key(self.CACHE_KEY)) <= 5

        # The lost claim left the registry, so later cycles cannot revive the key either.
        self.redis.delete(_claim_redis_key(self.CACHE_KEY))
        _refresh_active_claims()
        assert not self.redis.exists(_claim_redis_key(self.CACHE_KEY))
        release_claim(claim)

    def test_wait_returns_result_ready_when_result_lands(self):
        self._store_entry("2026-08-20T00:00:00+00:00")
        claim = acquire_claim(self.CACHE_KEY)
        assert claim is not None

        def store_new_result(_seconds: float) -> None:
            self._store_entry("2026-08-20T00:01:00+00:00")

        outcome = wait_for_cached_result(self.CACHE_KEY, team_id=1, deadline=10**9, sleep=store_new_result)
        assert outcome == WaitOutcome.RESULT_READY
        release_claim(claim)

    def test_wait_returns_claim_released_when_claim_vanishes_without_result(self):
        claim = acquire_claim(self.CACHE_KEY)
        assert claim is not None

        def release_it(_seconds: float) -> None:
            release_claim(claim)

        outcome = wait_for_cached_result(self.CACHE_KEY, team_id=1, deadline=10**9, sleep=release_it)
        assert outcome == WaitOutcome.CLAIM_RELEASED

    def test_wait_rechecks_freshness_when_release_lands_mid_iteration(self):
        # The runner stores, then releases. A waiter that read freshness just before the
        # store and the claim just after the release must join the result, not recompute.
        freshness_sequence = iter(
            [
                EntryFreshness(last_refresh="old"),  # snapshot
                EntryFreshness(last_refresh="old"),  # first poll, before the store landed
                EntryFreshness(last_refresh="new"),  # re-check after the claim vanished
            ]
        )
        with patch(
            "posthog.query_cache.inflight.fetch_entry_freshness", side_effect=lambda *a, **k: next(freshness_sequence)
        ):
            outcome = wait_for_cached_result(self.CACHE_KEY, team_id=1, deadline=10**9)
        assert outcome == WaitOutcome.RESULT_READY

    def test_wait_times_out_while_claim_held(self):
        claim = acquire_claim(self.CACHE_KEY)
        assert claim is not None
        clock = iter([0.0, 0.0, 5.0, 10.0, 15.0])

        outcome = wait_for_cached_result(
            self.CACHE_KEY,
            team_id=1,
            deadline=9.0,
            monotonic=lambda: next(clock),
            sleep=lambda _seconds: None,
        )
        assert outcome == WaitOutcome.TIMED_OUT
        release_claim(claim)

    def test_eviction_is_not_a_result(self):
        self._store_entry("2026-08-20T00:00:00+00:00")
        claim = acquire_claim(self.CACHE_KEY)
        assert claim is not None

        def evict_then_release(_seconds: float) -> None:
            self.redis.delete(storage.entry_redis_key(self.CACHE_KEY))
            release_claim(claim)

        outcome = wait_for_cached_result(self.CACHE_KEY, team_id=1, deadline=10**9, sleep=evict_then_release)
        assert outcome == WaitOutcome.CLAIM_RELEASED

    def test_acquire_grants_unstored_claim_when_redis_is_down(self):
        with patch.object(storage, "query_cache_raw_client", side_effect=RuntimeError("redis down")):
            claim = acquire_claim(self.CACHE_KEY)
            assert claim is not None
            release_claim(claim)
        assert not self.redis.exists(_claim_redis_key(self.CACHE_KEY))
