import time
import threading
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import mock

from django.test import TestCase

from parameterized import parameterized
from redis.exceptions import RedisError

from posthog import redis as posthog_redis
from posthog.api.query_coalescer import (
    DONE_KEY_PREFIX,
    ERROR_KEY_PREFIX,
    LOCK_KEY_PREFIX,
    CoalesceSignal,
    QueryCoalescer,
    query_coalesce_counter,
)


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

    # -- Store / retrieve --

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

    def test_store_and_get_success_response(self):
        coalescer = QueryCoalescer(self.key)
        coalescer.try_acquire()
        coalescer.store_success_response(200, b'{"results": [1, 2, 3]}', "application/json")
        result = coalescer.get_success_response()
        assert result is not None
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["body"], '{"results": [1, 2, 3]}')
        self.assertEqual(result["content_type"], "application/json")
        coalescer.cleanup()

    def test_get_success_response_returns_none_when_missing(self):
        coalescer = QueryCoalescer(self.key)
        self.assertIsNone(coalescer.get_success_response())

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
            c.store_success_response(200, b'{"ok": true}', "application/json")
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


class TestQueryCoalescingMiddleware(ClickhouseTestMixin, APIBaseTest):
    def _query_url(self):
        return f"/api/environments/{self.team.id}/query/"

    def _query_payload(self):
        return {"query": {"kind": "EventsQuery", "select": ["event"]}}

    def test_leader_executes_and_stores_response(self):
        _create_event(team=self.team, event="test_event", distinct_id="user1")
        flush_persons_and_events()

        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = True

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(self._query_url(), self._query_payload())

        self.assertEqual(response.status_code, 200)
        mock_coalescer.store_success_response.assert_called_once()
        mock_coalescer.cleanup.assert_called_once()

    def test_leader_signals_error_on_4xx(self):
        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = True

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(
                self._query_url(),
                {"query": {"kind": "EventsQuery", "select": ["nonexistent_column_xyz"]}},
            )

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        # 4xx should signal error without storing response
        mock_coalescer.signal_error.assert_called_once()
        mock_coalescer.store_success_response.assert_not_called()
        mock_coalescer.cleanup.assert_called_once()

    def test_dry_run_follower_executes_normally(self):
        _create_event(team=self.team, event="test_event", distinct_id="user1")
        flush_persons_and_events()

        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = False
        mock_coalescer._dry_run = True

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=False),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(self._query_url(), self._query_payload())

        self.assertEqual(response.status_code, 200)
        events = [row[0] for row in response.json()["results"]]
        self.assertIn("test_event", events)
        mock_coalescer.wait_for_signal.assert_not_called()

    def test_follower_gets_replayed_success_response(self):
        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = False
        mock_coalescer._dry_run = False
        mock_coalescer.wait_for_signal.return_value = CoalesceSignal.DONE
        mock_coalescer.get_success_response.return_value = {
            "status": 200,
            "body": '{"results": [["test_event"]], "is_cached": true}',
            "content_type": "application/json",
        }

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(self._query_url(), self._query_payload())

        self.assertEqual(response.status_code, 200)
        self.assertIn("test_event", response.json()["results"][0][0])

    def test_follower_falls_through_on_error_signal(self):
        _create_event(team=self.team, event="test_event", distinct_id="user1")
        flush_persons_and_events()

        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = False
        mock_coalescer._dry_run = False
        mock_coalescer.wait_for_signal.return_value = CoalesceSignal.ERROR

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(self._query_url(), self._query_payload())

        # Follower executes independently on ERROR signal (leader had 4xx)
        self.assertEqual(response.status_code, 200)
        events = [row[0] for row in response.json()["results"]]
        self.assertIn("test_event", events)

    def test_follower_falls_through_on_timeout(self):
        _create_event(team=self.team, event="test_event", distinct_id="user1")
        flush_persons_and_events()

        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = False
        mock_coalescer._dry_run = False
        mock_coalescer.wait_for_signal.return_value = CoalesceSignal.TIMEOUT

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(self._query_url(), self._query_payload())

        self.assertEqual(response.status_code, 200)
        events = [row[0] for row in response.json()["results"]]
        self.assertIn("test_event", events)

    def test_follower_falls_through_on_crash(self):
        _create_event(team=self.team, event="test_event", distinct_id="user1")
        flush_persons_and_events()

        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = False
        mock_coalescer._dry_run = False
        mock_coalescer.wait_for_signal.return_value = CoalesceSignal.CRASHED

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(self._query_url(), self._query_payload())

        self.assertEqual(response.status_code, 200)
        events = [row[0] for row in response.json()["results"]]
        self.assertIn("test_event", events)

    def test_redis_failure_falls_through(self):
        _create_event(team=self.team, event="test_event", distinct_id="user1")
        flush_persons_and_events()

        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.side_effect = RedisError("down")

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(self._query_url(), self._query_payload())

        self.assertEqual(response.status_code, 200)
        events = [row[0] for row in response.json()["results"]]
        self.assertIn("test_event", events)

    def test_non_matching_path_skips_coalescing(self):
        with mock.patch("posthog.api.query_coalescer.QueryCoalescer") as mock_cls:
            self.client.get(f"/api/environments/{self.team.id}/annotations/")
            mock_cls.assert_not_called()

    def test_follower_gets_replayed_5xx_response(self):
        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = False
        mock_coalescer._dry_run = False
        mock_coalescer.wait_for_signal.return_value = CoalesceSignal.DONE
        mock_coalescer.get_success_response.return_value = {
            "status": 500,
            "body": '{"type": "server_error", "detail": "Internal server error"}',
            "content_type": "application/json",
        }

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer),
        ):
            response = self.client.post(self._query_url(), self._query_payload())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Internal server error")

    @parameterized.expand(
        [
            ("query", "/api/environments/{team_id}/query/"),
            ("insights_trend", "/api/environments/{team_id}/insights/trend/"),
            ("insights_funnel", "/api/environments/{team_id}/insights/funnel/"),
            ("insights_pk", "/api/environments/{team_id}/insights/123/"),
        ]
    )
    def test_matching_paths_trigger_coalescing(self, _name, path_template):
        path = path_template.format(team_id=self.team.id)
        mock_coalescer = mock.MagicMock()
        mock_coalescer.try_acquire.return_value = True

        with (
            mock.patch("posthog.api.query_coalescer.posthoganalytics.feature_enabled", return_value=True),
            mock.patch("posthog.api.query_coalescer.QueryCoalescer", return_value=mock_coalescer) as mock_cls,
        ):
            self.client.post(path, {"query": {"kind": "EventsQuery", "select": ["event"]}})
            mock_cls.assert_called_once()
