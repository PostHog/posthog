import time
import threading
from typing import Optional

from unittest import mock

from django.test import TestCase

from redis.exceptions import RedisError

from posthog import redis as posthog_redis
from posthog.hogql_queries.query_coalescer import (
    DONE_KEY_PREFIX,
    ERROR_KEY_PREFIX,
    LOCK_KEY_PREFIX,
    QueryCoalescer,
    QueryCoalescingError,
    _Heartbeat,
)


class TestQueryCoalescer(TestCase):
    def setUp(self):
        self.redis = posthog_redis.get_client()
        self.cache_key = f"test_{id(self)}_{time.monotonic_ns()}"

    def tearDown(self):
        self.redis.delete(f"{LOCK_KEY_PREFIX}:{self.cache_key}")
        self.redis.delete(f"{DONE_KEY_PREFIX}:{self.cache_key}")
        self.redis.delete(f"{ERROR_KEY_PREFIX}:{self.cache_key}")

    def _set_lock(self, query_id="leader"):
        self.redis.set(
            f"{LOCK_KEY_PREFIX}:{self.cache_key}",
            query_id,
            ex=60,
        )

    def _lock_exists(self) -> bool:
        return self.redis.get(f"{LOCK_KEY_PREFIX}:{self.cache_key}") is not None

    def _set_done(self):
        self.redis.set(f"{DONE_KEY_PREFIX}:{self.cache_key}", "1", ex=60)

    # -- Lock lifecycle --

    def test_acquire_succeeds_when_no_lock_exists(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        self.assertTrue(coalescer._try_acquire())
        self.assertTrue(self._lock_exists())

    def test_acquire_fails_when_lock_already_held(self):
        self._set_lock("other-leader")
        coalescer = QueryCoalescer(self.cache_key, "q1")
        self.assertFalse(coalescer._try_acquire())

    def test_release_deletes_own_lock(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        coalescer._try_acquire()
        coalescer._release()
        self.assertFalse(self._lock_exists())

    def test_release_preserves_other_leaders_lock(self):
        old_leader = QueryCoalescer(self.cache_key, "old")
        old_leader._try_acquire()
        # Simulate: old lock TTL expired, new leader acquired
        self.redis.delete(f"{LOCK_KEY_PREFIX}:{self.cache_key}")
        new_leader = QueryCoalescer(self.cache_key, "new")
        new_leader._try_acquire()
        old_leader._release()
        self.assertTrue(self._lock_exists())

    # -- Heartbeat --

    def test_heartbeat_extends_lock_ttl(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        coalescer._try_acquire()

        # Set a short TTL that would expire without heartbeat
        self.redis.expire(f"{LOCK_KEY_PREFIX}:{self.cache_key}", 2)
        ttl_before = self.redis.ttl(f"{LOCK_KEY_PREFIX}:{self.cache_key}")
        self.assertLessEqual(ttl_before, 2)

        heartbeat = _Heartbeat(self.redis, coalescer._lock_key, coalescer._lock_value)
        try:
            # Trigger a heartbeat by using a very short interval
            with mock.patch("posthog.hogql_queries.query_coalescer.HEARTBEAT_INTERVAL_SECONDS", 0.1):
                hb = _Heartbeat(self.redis, coalescer._lock_key, coalescer._lock_value)
                time.sleep(0.3)
                hb.stop()

            ttl_after = self.redis.ttl(f"{LOCK_KEY_PREFIX}:{self.cache_key}")
            self.assertGreater(ttl_after, 2)
        finally:
            heartbeat.stop()
            coalescer._release()

    def test_heartbeat_stops_cleanly(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        coalescer._try_acquire()
        heartbeat = _Heartbeat(self.redis, coalescer._lock_key, coalescer._lock_value)
        heartbeat.stop()
        self.assertFalse(heartbeat._thread.is_alive())
        coalescer._release()

    # -- Waiting for result --

    def test_wait_returns_none_when_leader_already_gone(self):
        coalescer = QueryCoalescer(self.cache_key, "follower")
        result = coalescer._wait_for_result(lambda: None, poll_interval=0, max_wait=0.01)
        self.assertIsNone(result)

    def test_wait_returns_cache_when_done_key_set(self):
        self._set_lock()
        self._set_done()
        coalescer = QueryCoalescer(self.cache_key, "follower")
        cache_data = {"results": [1]}
        result = coalescer._wait_for_result(lambda: cache_data, poll_interval=0, max_wait=5)
        self.assertEqual(result, cache_data)

    def test_wait_returns_none_when_error_key_set(self):
        self._set_lock()
        self.redis.set(f"{ERROR_KEY_PREFIX}:{self.cache_key}", "ValueError: boom", ex=60)
        coalescer = QueryCoalescer(self.cache_key, "follower")
        result = coalescer._wait_for_result(lambda: {"results": [1]}, poll_interval=0, max_wait=5)
        self.assertIsNone(result)

    def test_wait_skipped_in_dry_run(self):
        self._set_lock()
        self._set_done()
        coalescer = QueryCoalescer(self.cache_key, "follower", dry_run=True)
        result = coalescer._wait_for_result(
            lambda: {"results": [1]},
            poll_interval=0,
            max_wait=5,
        )
        self.assertIsNone(result)

    def test_wait_polls_until_done_key_appears(self):
        self._set_lock()
        coalescer = QueryCoalescer(self.cache_key, "follower")

        # Simulate leader finishing after a short delay
        def leader_finishes():
            time.sleep(0.05)
            self._set_done()

        t = threading.Thread(target=leader_finishes)
        t.start()

        result = coalescer._wait_for_result(lambda: {"ready": True}, poll_interval=0.01, max_wait=5)
        t.join()
        self.assertIsNotNone(result)

    def test_wait_returns_none_when_leader_gone_no_done(self):
        self._set_lock()
        coalescer = QueryCoalescer(self.cache_key, "follower")
        call_count = 0

        def no_cache_leader_dies():
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                self.redis.delete(f"{LOCK_KEY_PREFIX}:{self.cache_key}")
            return None

        result = coalescer._wait_for_result(no_cache_leader_dies, poll_interval=0.01, max_wait=5)
        self.assertIsNone(result)

    # -- run_coalesced end-to-end --

    def test_leader_executes_and_releases_lock(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        result = coalescer.run_coalesced(
            execute=lambda: "computed",
            get_cache_data=lambda: None,
            build_response=lambda data: "from_cache",
            max_wait=300,
        )
        self.assertEqual(result, "computed")
        self.assertFalse(self._lock_exists())

    def test_leader_starts_and_stops_heartbeat(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        with mock.patch("posthog.hogql_queries.query_coalescer._Heartbeat") as MockHB:
            coalescer.run_coalesced(
                execute=lambda: "computed",
                get_cache_data=lambda: None,
                build_response=lambda data: "from_cache",
                max_wait=300,
            )
        MockHB.assert_called_once()
        MockHB.return_value.stop.assert_called_once()

    def test_leader_stops_heartbeat_on_exception(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        with mock.patch("posthog.hogql_queries.query_coalescer._Heartbeat") as MockHB:
            with self.assertRaises(ValueError):
                coalescer.run_coalesced(
                    execute=_raise_value_error,
                    get_cache_data=lambda: None,
                    build_response=lambda data: "from_cache",
                    max_wait=300,
                )
        MockHB.return_value.stop.assert_called_once()

    def test_follower_returns_cached_result(self):
        self._set_lock()
        self._set_done()
        coalescer = QueryCoalescer(self.cache_key, "follower")
        execute_called = False

        def should_not_execute():
            nonlocal execute_called
            execute_called = True
            return "should_not_happen"

        result = coalescer.run_coalesced(
            execute=should_not_execute,
            get_cache_data=lambda: {"results": [1]},
            build_response=lambda data: data["results"],
            max_wait=300,
        )
        self.assertEqual(result, [1])
        self.assertFalse(execute_called)

    def test_follower_raises_when_leader_fails(self):
        coalescer = QueryCoalescer(self.cache_key, "follower")
        coalescer._store_error(ValueError("ClickHouse timeout"))

        def follower_acquire():
            self._set_lock()
            return False

        with mock.patch.object(coalescer, "_try_acquire", side_effect=follower_acquire):
            with mock.patch.object(coalescer, "_wait_for_result", return_value=None):
                with self.assertRaises(QueryCoalescingError) as ctx:
                    coalescer.run_coalesced(
                        execute=lambda: "should_not_run",
                        get_cache_data=lambda: None,
                        build_response=lambda data: "from_cache",
                        max_wait=300,
                    )

        self.assertIn("ValueError: ClickHouse timeout", str(ctx.exception))

    def test_follower_raises_when_leader_crashes_without_error(self):
        coalescer = QueryCoalescer(self.cache_key, "follower")

        def follower_acquire():
            self._set_lock()
            return False

        with mock.patch.object(coalescer, "_try_acquire", side_effect=follower_acquire):
            with mock.patch.object(coalescer, "_wait_for_result", return_value=None):
                with self.assertRaises(QueryCoalescingError) as ctx:
                    coalescer.run_coalesced(
                        execute=lambda: "should_not_run",
                        get_cache_data=lambda: None,
                        build_response=lambda data: "from_cache",
                        max_wait=300,
                    )

        self.assertIn("Leader failed or crashed", str(ctx.exception))

    def test_follower_raises_when_max_wait_exceeded(self):
        self._set_lock()
        coalescer = QueryCoalescer(self.cache_key, "follower")
        with self.assertRaises(QueryCoalescingError):
            coalescer.run_coalesced(
                execute=lambda: "should_not_run",
                get_cache_data=lambda: None,
                build_response=lambda data: "from_cache",
                max_wait=0.01,
            )

    def test_leader_exception_releases_lock(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        with self.assertRaises(ValueError):
            coalescer.run_coalesced(
                execute=_raise_value_error,
                get_cache_data=lambda: None,
                build_response=lambda data: "from_cache",
                max_wait=300,
            )
        self.assertFalse(self._lock_exists())

    def test_redis_failure_falls_back_to_execute(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        with mock.patch.object(coalescer, "_try_acquire", side_effect=RedisError("down")):
            result = coalescer.run_coalesced(
                execute=lambda: "fallback",
                get_cache_data=lambda: None,
                build_response=lambda data: "from_cache",
                max_wait=300,
            )
        self.assertEqual(result, "fallback")

    def test_dry_run_follower_executes_independently(self):
        self._set_lock()
        coalescer = QueryCoalescer(self.cache_key, "follower", dry_run=True)
        result = coalescer.run_coalesced(
            execute=lambda: "independent",
            get_cache_data=lambda: {"cached": True},
            build_response=lambda data: "from_cache",
            max_wait=300,
        )
        self.assertEqual(result, "independent")

    def test_leader_exception_stored_in_redis(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        with self.assertRaises(ValueError):
            coalescer.run_coalesced(
                execute=_raise_value_error,
                get_cache_data=lambda: None,
                build_response=lambda data: "from_cache",
                max_wait=300,
            )

        error_value = self.redis.get(f"{ERROR_KEY_PREFIX}:{self.cache_key}")
        assert error_value is not None
        self.assertIn(b"ValueError: boom", error_value)

    def test_leader_heartbeat_keeps_followers_waiting(self):
        """Long-running leader with heartbeat: followers still get result."""
        follower_waiting = threading.Event()
        leader_done = threading.Event()
        follower_result: list[Optional[dict]] = [None]

        coalescer = QueryCoalescer(self.cache_key, "leader")
        coalescer._try_acquire()

        def get_cache():
            if leader_done.is_set():
                return {"results": [42]}
            return None

        def run_follower():
            follower = QueryCoalescer(self.cache_key, "follower")
            follower_waiting.set()
            follower_result[0] = follower._wait_for_result(get_cache, poll_interval=0.05, max_wait=5)

        follower_thread = threading.Thread(target=run_follower)
        follower_thread.start()

        # Wait for follower to start polling, then simulate leader finishing
        follower_waiting.wait(timeout=2)
        time.sleep(0.1)
        leader_done.set()
        self._set_done()
        # Release lock after cache is available (simulates leader's finally block)
        time.sleep(0.05)
        coalescer._release()

        follower_thread.join(timeout=5)
        assert follower_result[0] is not None
        self.assertEqual(follower_result[0]["results"], [42])


def _raise_value_error():
    raise ValueError("boom")
