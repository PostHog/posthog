import json
import time
import itertools
import threading
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import mock

from django.test import TestCase

from redis.exceptions import RedisError

from posthog import redis as posthog_redis
from posthog.api.query_coalescer import (
    _EXTEND_LOCK_SCRIPT,
    CHANNEL_PREFIX,
    DONE_KEY_PREFIX,
    ERROR_KEY_PREFIX,
    LOCK_KEY_PREFIX,
    LOCK_TTL_SECONDS,
    CoalesceSignal,
    QueryCoalescer,
    compute_coalescing_key,
    query_coalesce_counter,
)


def _fake_clock(step: float):
    """Return a callable that advances by `step` on each call, replacing time.monotonic."""
    counter = itertools.count()
    return lambda: next(counter) * step


class TestComputeCoalescingKey(TestCase):
    def test_same_inputs_produce_same_key(self):
        key1 = compute_coalescing_key(1, '{"kind": "TrendsQuery"}')
        key2 = compute_coalescing_key(1, '{"kind": "TrendsQuery"}')
        self.assertEqual(key1, key2)

    def test_different_team_produces_different_key(self):
        key1 = compute_coalescing_key(1, '{"kind": "TrendsQuery"}')
        key2 = compute_coalescing_key(2, '{"kind": "TrendsQuery"}')
        self.assertNotEqual(key1, key2)

    def test_different_query_produces_different_key(self):
        key1 = compute_coalescing_key(1, '{"kind": "TrendsQuery"}')
        key2 = compute_coalescing_key(1, '{"kind": "FunnelsQuery"}')
        self.assertNotEqual(key1, key2)


class TestQueryCoalescer(TestCase):
    def setUp(self):
        self.redis = posthog_redis.get_client()
        self.key = f"test_{id(self)}_{time.monotonic_ns()}"

    def tearDown(self):
        self.redis.delete(f"{LOCK_KEY_PREFIX}:{self.key}")
        self.redis.delete(f"{DONE_KEY_PREFIX}:{self.key}")
        self.redis.delete(f"{ERROR_KEY_PREFIX}:{self.key}")

    def _set_lock(self, value="leader"):
        self.redis.set(f"{LOCK_KEY_PREFIX}:{self.key}", value, ex=60)

    def _lock_exists(self) -> bool:
        return self.redis.get(f"{LOCK_KEY_PREFIX}:{self.key}") is not None

    # -- Lock lifecycle --

    def test_acquire_succeeds_when_no_lock(self):
        coalescer = QueryCoalescer(self.key)
        self.assertTrue(coalescer.try_acquire())
        self.assertTrue(coalescer.is_leader)
        self.assertTrue(self._lock_exists())
        coalescer.cleanup()

    def test_acquire_fails_when_lock_held(self):
        self._set_lock("other")
        coalescer = QueryCoalescer(self.key)
        self.assertFalse(coalescer.try_acquire())
        self.assertFalse(coalescer.is_leader)

    def test_cleanup_releases_lock(self):
        coalescer = QueryCoalescer(self.key)
        coalescer.try_acquire()
        coalescer.cleanup()
        self.assertFalse(self._lock_exists())

    def test_cleanup_preserves_other_leaders_lock(self):
        old = QueryCoalescer(self.key)
        old.try_acquire()
        # Simulate old lock expired, new leader acquired
        self.redis.delete(f"{LOCK_KEY_PREFIX}:{self.key}")
        new = QueryCoalescer(self.key)
        new.try_acquire()
        old.cleanup()
        self.assertTrue(self._lock_exists())
        new.cleanup()

    # -- Heartbeat --

    def test_extend_lock_script_refreshes_ttl(self):
        coalescer = QueryCoalescer(self.key)
        coalescer.try_acquire()

        self.redis.expire(f"{LOCK_KEY_PREFIX}:{self.key}", 2)
        self.assertLessEqual(self.redis.ttl(f"{LOCK_KEY_PREFIX}:{self.key}"), 2)

        self.redis.eval(_EXTEND_LOCK_SCRIPT, 1, coalescer._lock_key, coalescer._lock_value, LOCK_TTL_SECONDS)

        self.assertGreater(self.redis.ttl(f"{LOCK_KEY_PREFIX}:{self.key}"), 2)
        coalescer.cleanup()

    def test_heartbeat_stops_cleanly(self):
        coalescer = QueryCoalescer(self.key)
        coalescer.try_acquire()
        assert coalescer._heartbeat is not None
        heartbeat = coalescer._heartbeat
        coalescer.cleanup()
        self.assertFalse(heartbeat._thread.is_alive())

    # -- Signals --

    def test_mark_done_sets_done_key(self):
        coalescer = QueryCoalescer(self.key)
        coalescer.try_acquire()
        coalescer.mark_done()
        self.assertIsNotNone(self.redis.get(f"{DONE_KEY_PREFIX}:{self.key}"))
        coalescer.cleanup()

    def test_store_and_get_error_response(self):
        coalescer = QueryCoalescer(self.key)
        coalescer.try_acquire()
        coalescer.store_error_response(400, b'{"detail":"bad request"}')
        result = coalescer.get_error_response()
        assert result is not None
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["body"], '{"detail":"bad request"}')
        coalescer.cleanup()

    def test_get_error_response_returns_none_when_missing(self):
        coalescer = QueryCoalescer(self.key)
        self.assertIsNone(coalescer.get_error_response())

    # -- wait_for_signal --

    def test_wait_returns_done_when_done_key_set(self):
        self._set_lock()
        self.redis.set(f"{DONE_KEY_PREFIX}:{self.key}", "1", ex=60)
        coalescer = QueryCoalescer(self.key)
        self.assertEqual(coalescer.wait_for_signal(max_wait=5), CoalesceSignal.DONE)

    def test_wait_returns_error_when_error_key_set(self):
        self._set_lock()
        self.redis.set(
            f"{ERROR_KEY_PREFIX}:{self.key}",
            json.dumps({"status": 500, "body": "internal error"}),
            ex=60,
        )
        coalescer = QueryCoalescer(self.key)
        self.assertEqual(coalescer.wait_for_signal(max_wait=5), CoalesceSignal.ERROR)

    def test_wait_returns_crashed_when_no_heartbeat(self):
        coalescer = QueryCoalescer(self.key)
        # Each call advances 25s. crash_timeout = 2 * 20 = 40s.
        # Iteration 1: elapsed=25, last_message=0 → 25 < 40, no crash yet
        # Iteration 2: elapsed=50, last_message=0 → 50 > 40, CRASHED
        clock = _fake_clock(step=25)
        with mock.patch("posthog.api.query_coalescer.time.monotonic", clock):
            self.assertEqual(coalescer.wait_for_signal(max_wait=300), CoalesceSignal.CRASHED)

    def test_wait_returns_crashed_when_heartbeat_stops(self):
        coalescer = QueryCoalescer(self.key)
        channel = f"{CHANNEL_PREFIX}:{self.key}"

        # Publish heartbeats for the first 3 get_message calls, then stop
        call_count = 0
        original_get_message = self.redis.pubsub().__class__.get_message

        def get_message_with_initial_heartbeats(ps, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                self.redis.publish(channel, "heartbeat")
            return original_get_message(ps, *args, **kwargs)

        # Each call advances 15s. crash_timeout = 40s.
        # Iterations 1-3: heartbeat received → last_message resets
        # Iteration 4: no heartbeat, elapsed since last_message=15 < 40
        # Iteration 5: no heartbeat, elapsed since last_message=30 < 40
        # Iteration 6: no heartbeat, elapsed since last_message=45 > 40 → CRASHED
        clock = _fake_clock(step=15)
        with (
            mock.patch("posthog.api.query_coalescer.time.monotonic", clock),
            mock.patch("redis.client.PubSub.get_message", get_message_with_initial_heartbeats),
        ):
            self.assertEqual(coalescer.wait_for_signal(max_wait=300), CoalesceSignal.CRASHED)

    def test_wait_returns_timeout_when_max_wait_exceeded(self):
        self._set_lock()
        coalescer = QueryCoalescer(self.key)
        # First call returns 0 (start), next returns 100 → exceeds max_wait
        clock = _fake_clock(step=100)
        with mock.patch("posthog.api.query_coalescer.time.monotonic", clock):
            self.assertEqual(coalescer.wait_for_signal(max_wait=50), CoalesceSignal.TIMEOUT)

    # -- Concurrent leader + follower --

    def test_concurrent_leader_and_follower(self):
        results: dict[str, Any] = {}
        barrier = threading.Barrier(2, timeout=5)

        follower_polling = threading.Event()

        def run_leader():
            c = QueryCoalescer(self.key)
            acquired = c.try_acquire()
            results["leader_acquired"] = acquired
            barrier.wait()
            follower_polling.wait(timeout=5)
            c.mark_done()
            c.cleanup()

        def run_follower():
            barrier.wait()
            c = QueryCoalescer(self.key)
            acquired = c.try_acquire()
            results["follower_acquired"] = acquired
            follower_polling.set()
            signal = c.wait_for_signal(max_wait=5)
            results["follower_signal"] = signal

        leader_thread = threading.Thread(target=run_leader)
        follower_thread = threading.Thread(target=run_follower)
        leader_thread.start()
        follower_thread.start()
        leader_thread.join(timeout=10)
        follower_thread.join(timeout=10)

        self.assertTrue(results["leader_acquired"])
        self.assertFalse(results["follower_acquired"])
        self.assertEqual(results["follower_signal"], CoalesceSignal.DONE)

    def test_concurrent_leader_error_and_follower(self):
        results: dict[str, Any] = {}
        barrier = threading.Barrier(2, timeout=5)
        follower_polling = threading.Event()

        def run_leader():
            c = QueryCoalescer(self.key)
            c.try_acquire()
            barrier.wait()
            follower_polling.wait(timeout=5)
            c.store_error_response(500, b'{"detail":"server error"}')
            c.cleanup()

        def run_follower():
            barrier.wait()
            c = QueryCoalescer(self.key)
            c.try_acquire()
            follower_polling.set()
            signal = c.wait_for_signal(max_wait=5)
            results["signal"] = signal
            if signal == CoalesceSignal.ERROR:
                results["error_data"] = c.get_error_response()

        leader_thread = threading.Thread(target=run_leader)
        follower_thread = threading.Thread(target=run_follower)
        leader_thread.start()
        follower_thread.start()
        leader_thread.join(timeout=10)
        follower_thread.join(timeout=10)

        self.assertEqual(results["signal"], CoalesceSignal.ERROR)
        self.assertEqual(results["error_data"]["status"], 500)
        self.assertEqual(results["error_data"]["body"], '{"detail":"server error"}')

    # -- Metrics --

    def test_leader_increments_counter(self):
        from posthog.api.query_coalescer import query_coalesce_counter

        before = query_coalesce_counter.labels(outcome="leader")._value.get()
        coalescer = QueryCoalescer(self.key)
        coalescer.try_acquire()
        after = query_coalesce_counter.labels(outcome="leader")._value.get()
        self.assertEqual(after, before + 1)
        coalescer.cleanup()

    def test_follower_increments_counter(self):
        from posthog.api.query_coalescer import query_coalesce_counter

        self._set_lock()
        before = query_coalesce_counter.labels(outcome="follower")._value.get()
        coalescer = QueryCoalescer(self.key)
        coalescer.try_acquire()
        after = query_coalesce_counter.labels(outcome="follower")._value.get()
        self.assertEqual(after, before + 1)

    def test_dry_run_follower_increments_counter(self):
        self._set_lock()
        before = query_coalesce_counter.labels(outcome="follower_dry_run")._value.get()
        coalescer = QueryCoalescer(self.key, dry_run=True)
        self.assertFalse(coalescer.try_acquire())
        after = query_coalesce_counter.labels(outcome="follower_dry_run")._value.get()
        self.assertEqual(after, before + 1)

    # -- Redis failure --

    def test_redis_failure_on_acquire_raises(self):
        coalescer = QueryCoalescer(self.key)
        with mock.patch.object(coalescer._redis, "set", side_effect=RedisError("down")):
            with self.assertRaises(RedisError):
                coalescer.try_acquire()


class TestQueryCoalescingEndpoint(ClickhouseTestMixin, APIBaseTest):
    def _query_and_key(self):
        from posthog.schema import EventsQuery

        query = EventsQuery(select=["event"])
        key = compute_coalescing_key(self.team.pk, query.model_dump_json())
        return query, key

    def test_dry_run_follower_executes_normally(self):
        _create_event(team=self.team, event="test_event", distinct_id="user1")
        flush_persons_and_events()

        query, key = self._query_and_key()
        redis = posthog_redis.get_client()
        redis.set(f"{LOCK_KEY_PREFIX}:{key}", "other_leader", ex=60)

        before = query_coalesce_counter.labels(outcome="follower_dry_run")._value.get()

        try:
            with (
                mock.patch("posthog.api.query.posthoganalytics.feature_enabled", return_value=False),
                mock.patch.object(QueryCoalescer, "wait_for_signal") as mock_wait,
            ):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/query/",
                    {"query": query.model_dump()},
                )

            self.assertEqual(response.status_code, 200)
            events = [row[0] for row in response.json()["results"]]
            self.assertIn("test_event", events)
            after = query_coalesce_counter.labels(outcome="follower_dry_run")._value.get()
            self.assertEqual(after, before + 1)
            mock_wait.assert_not_called()
        finally:
            redis.delete(f"{LOCK_KEY_PREFIX}:{key}")

    def test_follower_waits_for_leader_and_hits_cache(self):
        _create_event(team=self.team, event="test_event", distinct_id="user1")
        flush_persons_and_events()

        query, key = self._query_and_key()

        # First request populates the cache (as leader, no lock held)
        with mock.patch("posthog.api.query.posthoganalytics.feature_enabled", return_value=True):
            first = self.client.post(
                f"/api/environments/{self.team.id}/query/",
                {"query": query.model_dump()},
            )
        self.assertEqual(first.status_code, 200)

        # Now simulate a leader holding the lock with done signal
        redis = posthog_redis.get_client()
        redis.set(f"{LOCK_KEY_PREFIX}:{key}", "other_leader", ex=60)
        redis.set(f"{DONE_KEY_PREFIX}:{key}", "1", ex=60)

        before_follower = query_coalesce_counter.labels(outcome="follower")._value.get()
        before_done = query_coalesce_counter.labels(outcome="follower_done")._value.get()

        try:
            with mock.patch("posthog.api.query.posthoganalytics.feature_enabled", return_value=True):
                response = self.client.post(
                    f"/api/environments/{self.team.id}/query/",
                    {"query": query.model_dump()},
                )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json().get("is_cached"))
            events = [row[0] for row in response.json()["results"]]
            self.assertIn("test_event", events)
            after_follower = query_coalesce_counter.labels(outcome="follower")._value.get()
            after_done = query_coalesce_counter.labels(outcome="follower_done")._value.get()
            self.assertEqual(after_follower, before_follower + 1)
            self.assertEqual(after_done, before_done + 1)
        finally:
            redis.delete(f"{LOCK_KEY_PREFIX}:{key}")
            redis.delete(f"{DONE_KEY_PREFIX}:{key}")
