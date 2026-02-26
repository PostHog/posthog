import time

from unittest import mock

from django.test import TestCase

from parameterized import parameterized
from redis.exceptions import RedisError

from posthog import redis as posthog_redis
from posthog.hogql_queries.query_coalescing import LOCK_KEY_PREFIX, QueryCoalescer


class TestQueryCoalescer(TestCase):
    def setUp(self):
        self.redis = posthog_redis.get_client()
        self.cache_key = f"test_{id(self)}_{time.monotonic_ns()}"

    def tearDown(self):
        self.redis.delete(f"{LOCK_KEY_PREFIX}:{self.cache_key}")

    def _set_lock(self, query_id="leader", timestamp=None):
        if timestamp is None:
            timestamp = time.time()
        self.redis.set(
            f"{LOCK_KEY_PREFIX}:{self.cache_key}",
            f"{query_id}:{timestamp}",
            ex=60,
        )

    def _lock_exists(self) -> bool:
        return self.redis.get(f"{LOCK_KEY_PREFIX}:{self.cache_key}") is not None

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

    # -- Waiting for result --

    @parameterized.expand(
        [
            ("cache_hit", True, 0, False, {"results": [1]}, {"results": [1]}),
            ("leader_gone", False, 0, False, None, None),
            ("leader_expired", True, -60, False, None, None),
            ("dry_run", True, 0, True, {"results": [1]}, None),
        ]
    )
    def test_wait_for_result(self, _name, has_lock, lock_age_offset, dry_run, cache_data, expected):
        if has_lock:
            self._set_lock(timestamp=time.time() + lock_age_offset)
        coalescer = QueryCoalescer(self.cache_key, "follower", dry_run=dry_run)
        result = coalescer._wait_for_result(lambda: cache_data, poll_interval=0, max_leader_age=30)
        self.assertEqual(result, expected)

    def test_wait_polls_until_cache_appears(self):
        self._set_lock()
        coalescer = QueryCoalescer(self.cache_key, "follower")
        call_count = 0

        def delayed_cache():
            nonlocal call_count
            call_count += 1
            return {"ready": True} if call_count >= 3 else None

        result = coalescer._wait_for_result(delayed_cache, poll_interval=0.01, max_leader_age=5)
        self.assertEqual(result, {"ready": True})
        self.assertEqual(call_count, 3)

    # -- run_coalesced end-to-end --

    def test_leader_executes_and_releases_lock(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        result = coalescer.run_coalesced(
            execute=lambda: "computed",
            get_cache_data=lambda: None,
            build_response=lambda data: "from_cache",
        )
        self.assertEqual(result, "computed")
        self.assertFalse(self._lock_exists())

    def test_follower_returns_cached_result(self):
        self._set_lock()
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
        )
        self.assertEqual(result, [1])
        self.assertFalse(execute_called)

    def test_follower_falls_back_on_timeout(self):
        self._set_lock(timestamp=time.time() - 60)
        coalescer = QueryCoalescer(self.cache_key, "follower")
        result = coalescer.run_coalesced(
            execute=lambda: "fallback",
            get_cache_data=lambda: None,
            build_response=lambda data: "from_cache",
        )
        self.assertEqual(result, "fallback")

    def test_leader_exception_releases_lock(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        with self.assertRaises(ValueError):
            coalescer.run_coalesced(
                execute=_raise_value_error,
                get_cache_data=lambda: None,
                build_response=lambda data: "from_cache",
            )
        self.assertFalse(self._lock_exists())

    def test_redis_failure_falls_back_to_execute(self):
        coalescer = QueryCoalescer(self.cache_key, "q1")
        with mock.patch.object(coalescer, "_try_acquire", side_effect=RedisError("down")):
            result = coalescer.run_coalesced(
                execute=lambda: "fallback",
                get_cache_data=lambda: None,
                build_response=lambda data: "from_cache",
            )
        self.assertEqual(result, "fallback")

    def test_dry_run_follower_executes_independently(self):
        self._set_lock()
        coalescer = QueryCoalescer(self.cache_key, "follower", dry_run=True)
        result = coalescer.run_coalesced(
            execute=lambda: "independent",
            get_cache_data=lambda: {"cached": True},
            build_response=lambda data: "from_cache",
        )
        self.assertEqual(result, "independent")


def _raise_value_error():
    raise ValueError("boom")
