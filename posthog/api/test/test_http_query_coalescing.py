import json
import time
import threading
from typing import Any

from unittest import mock

from django.test import TestCase

from redis.exceptions import RedisError

from posthog import redis as posthog_redis
from posthog.api.query_coalescer import (
    DONE_KEY_PREFIX,
    ERROR_KEY_PREFIX,
    LOCK_KEY_PREFIX,
    HttpQueryCoalescer,
    _Heartbeat,
    compute_coalescing_key,
)


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


class TestHttpQueryCoalescer(TestCase):
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
        coalescer = HttpQueryCoalescer(self.key)
        self.assertTrue(coalescer.try_acquire())
        self.assertTrue(coalescer.is_leader)
        self.assertTrue(self._lock_exists())
        coalescer.cleanup()

    def test_acquire_fails_when_lock_held(self):
        self._set_lock("other")
        coalescer = HttpQueryCoalescer(self.key)
        self.assertFalse(coalescer.try_acquire())
        self.assertFalse(coalescer.is_leader)

    def test_cleanup_releases_lock(self):
        coalescer = HttpQueryCoalescer(self.key)
        coalescer.try_acquire()
        coalescer.cleanup()
        self.assertFalse(self._lock_exists())

    def test_cleanup_preserves_other_leaders_lock(self):
        old = HttpQueryCoalescer(self.key)
        old.try_acquire()
        # Simulate old lock expired, new leader acquired
        self.redis.delete(f"{LOCK_KEY_PREFIX}:{self.key}")
        new = HttpQueryCoalescer(self.key)
        new.try_acquire()
        old.cleanup()
        self.assertTrue(self._lock_exists())
        new.cleanup()

    # -- Heartbeat --

    def test_heartbeat_extends_lock_ttl(self):
        coalescer = HttpQueryCoalescer(self.key)
        coalescer.try_acquire()

        self.redis.expire(f"{LOCK_KEY_PREFIX}:{self.key}", 2)
        ttl_before = self.redis.ttl(f"{LOCK_KEY_PREFIX}:{self.key}")
        self.assertLessEqual(ttl_before, 2)

        with mock.patch("posthog.api.query_coalescer.HEARTBEAT_INTERVAL_SECONDS", 0.1):
            hb = _Heartbeat(self.redis, coalescer._lock_key, coalescer._lock_value)
            time.sleep(0.3)
            hb.stop()

        ttl_after = self.redis.ttl(f"{LOCK_KEY_PREFIX}:{self.key}")
        self.assertGreater(ttl_after, 2)
        coalescer.cleanup()

    def test_heartbeat_stops_cleanly(self):
        coalescer = HttpQueryCoalescer(self.key)
        coalescer.try_acquire()
        assert coalescer._heartbeat is not None
        heartbeat = coalescer._heartbeat
        coalescer.cleanup()
        self.assertFalse(heartbeat._thread.is_alive())

    # -- Signals --

    def test_mark_done_sets_done_key(self):
        coalescer = HttpQueryCoalescer(self.key)
        coalescer.try_acquire()
        coalescer.mark_done()
        self.assertIsNotNone(self.redis.get(f"{DONE_KEY_PREFIX}:{self.key}"))
        coalescer.cleanup()

    def test_store_and_get_error_response(self):
        coalescer = HttpQueryCoalescer(self.key)
        coalescer.try_acquire()
        coalescer.store_error_response(400, b'{"detail":"bad request"}')
        result = coalescer.get_error_response()
        assert result is not None
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["body"], '{"detail":"bad request"}')
        coalescer.cleanup()

    def test_get_error_response_returns_none_when_missing(self):
        coalescer = HttpQueryCoalescer(self.key)
        self.assertIsNone(coalescer.get_error_response())

    # -- wait_for_signal --

    def test_wait_returns_done_when_done_key_set(self):
        self._set_lock()
        self.redis.set(f"{DONE_KEY_PREFIX}:{self.key}", "1", ex=60)
        coalescer = HttpQueryCoalescer(self.key)
        self.assertEqual(coalescer.wait_for_signal(max_wait=5), "done")

    def test_wait_returns_error_when_error_key_set(self):
        self._set_lock()
        self.redis.set(
            f"{ERROR_KEY_PREFIX}:{self.key}",
            json.dumps({"status": 500, "body": "internal error"}),
            ex=60,
        )
        coalescer = HttpQueryCoalescer(self.key)
        self.assertEqual(coalescer.wait_for_signal(max_wait=5), "error")

    def test_wait_returns_crashed_when_lock_gone(self):
        # No lock set — leader gone
        coalescer = HttpQueryCoalescer(self.key)
        self.assertEqual(coalescer.wait_for_signal(max_wait=0.1), "crashed")

    def test_wait_returns_timeout_when_max_wait_exceeded(self):
        self._set_lock()
        coalescer = HttpQueryCoalescer(self.key)
        self.assertEqual(coalescer.wait_for_signal(max_wait=0.01), "timeout")

    def test_wait_returns_timeout_in_dry_run(self):
        self._set_lock()
        self.redis.set(f"{DONE_KEY_PREFIX}:{self.key}", "1", ex=60)
        coalescer = HttpQueryCoalescer(self.key, dry_run=True)
        self.assertEqual(coalescer.wait_for_signal(max_wait=5), "timeout")

    def test_wait_polls_until_done(self):
        self._set_lock()
        coalescer = HttpQueryCoalescer(self.key)

        def leader_finishes():
            time.sleep(0.05)
            self.redis.set(f"{DONE_KEY_PREFIX}:{self.key}", "1", ex=60)

        t = threading.Thread(target=leader_finishes)
        t.start()
        self.assertEqual(coalescer.wait_for_signal(max_wait=5), "done")
        t.join()

    # -- Concurrent leader + follower --

    def test_concurrent_leader_and_follower(self):
        results: dict[str, Any] = {}
        barrier = threading.Barrier(2, timeout=5)

        follower_polling = threading.Event()

        def run_leader():
            c = HttpQueryCoalescer(self.key)
            acquired = c.try_acquire()
            results["leader_acquired"] = acquired
            barrier.wait()
            follower_polling.wait(timeout=5)
            c.mark_done()
            c.cleanup()

        def run_follower():
            barrier.wait()
            c = HttpQueryCoalescer(self.key)
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
        self.assertEqual(results["follower_signal"], "done")

    def test_concurrent_leader_error_and_follower(self):
        results: dict[str, Any] = {}
        barrier = threading.Barrier(2, timeout=5)
        follower_polling = threading.Event()

        def run_leader():
            c = HttpQueryCoalescer(self.key)
            c.try_acquire()
            barrier.wait()
            follower_polling.wait(timeout=5)
            c.store_error_response(500, b'{"detail":"server error"}')
            c.cleanup()

        def run_follower():
            barrier.wait()
            c = HttpQueryCoalescer(self.key)
            c.try_acquire()
            follower_polling.set()
            signal = c.wait_for_signal(max_wait=5)
            results["signal"] = signal
            if signal == "error":
                results["error_data"] = c.get_error_response()

        leader_thread = threading.Thread(target=run_leader)
        follower_thread = threading.Thread(target=run_follower)
        leader_thread.start()
        follower_thread.start()
        leader_thread.join(timeout=10)
        follower_thread.join(timeout=10)

        self.assertEqual(results["signal"], "error")
        self.assertEqual(results["error_data"]["status"], 500)
        self.assertEqual(results["error_data"]["body"], '{"detail":"server error"}')

    # -- Metrics --

    def test_leader_increments_counter(self):
        from posthog.api.query_coalescer import http_coalesce_counter

        before = http_coalesce_counter.labels(outcome="leader")._value.get()
        coalescer = HttpQueryCoalescer(self.key)
        coalescer.try_acquire()
        after = http_coalesce_counter.labels(outcome="leader")._value.get()
        self.assertEqual(after, before + 1)
        coalescer.cleanup()

    def test_follower_increments_counter(self):
        from posthog.api.query_coalescer import http_coalesce_counter

        self._set_lock()
        before = http_coalesce_counter.labels(outcome="follower")._value.get()
        coalescer = HttpQueryCoalescer(self.key)
        coalescer.try_acquire()
        after = http_coalesce_counter.labels(outcome="follower")._value.get()
        self.assertEqual(after, before + 1)

    def test_dry_run_follower_increments_counter(self):
        from posthog.api.query_coalescer import http_coalesce_counter

        self._set_lock()
        before = http_coalesce_counter.labels(outcome="follower_dry_run")._value.get()
        coalescer = HttpQueryCoalescer(self.key, dry_run=True)
        coalescer.try_acquire()
        after = http_coalesce_counter.labels(outcome="follower_dry_run")._value.get()
        self.assertEqual(after, before + 1)

    # -- Redis failure --

    def test_redis_failure_on_acquire_raises(self):
        coalescer = HttpQueryCoalescer(self.key)
        with mock.patch.object(coalescer._redis, "set", side_effect=RedisError("down")):
            with self.assertRaises(RedisError):
                coalescer.try_acquire()
