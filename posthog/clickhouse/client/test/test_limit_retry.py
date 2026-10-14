import random
from collections.abc import Callable
from dataclasses import replace

from unittest import TestCase
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.clickhouse.client.limit import (
    ConcurrencyLimitExceeded,
    RateLimit,
    get_api_team_rate_limiter,
    get_materialized_endpoints_rate_limiter,
)


class TestRetryTiming(TestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []
        self.limit = RateLimit(
            max_concurrency=3,
            limit_name="retry_timing",
            get_task_name=lambda **kwargs: "retry-timing",
            get_task_id=lambda **kwargs: kwargs["task_id"],
            retry=0.1,
            retry_timeout=0.5,
            apply_clickhouse_kill_switch=False,
            allow_team_bypass=False,
        )
        self.limit.redis_client = Mock()
        self.limit.get_time = lambda: self.now
        self.limit.sleep = self.advance

    def advance(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.now += duration

    @parameterized.expand([(False,), (True,)])
    def test_timeout_does_not_sleep_past_deadline(self, jitter: bool) -> None:
        self.limit.retry_jitter = jitter
        self.limit.redis_client.eval.return_value = 0
        with patch.object(random, "uniform", side_effect=lambda low, high: (low + high) / 2):
            with self.assertRaises(ConcurrencyLimitExceeded):
                self.limit.use(task_id="waiting")
        self.assertAlmostEqual(sum(self.sleeps), 0.5)
        self.limit.redis_client.zrem.assert_not_called()

    @parameterized.expand([(False, 0.1), (True, 0.075)])
    def test_released_slot_uses_selected_retry_delay(self, jitter: bool, expected_wait: float) -> None:
        self.limit.retry_jitter = jitter
        self.limit.redis_client.eval.side_effect = [0, 1]
        with patch.object(random, "uniform", side_effect=lambda low, high: (low + high) / 2):
            with self.limit.run(task_id="waiting"):
                self.assertAlmostEqual(sum(self.sleeps), expected_wait)
        self.limit.redis_client.zrem.assert_called_once_with("retry-timing", "waiting")

    @parameterized.expand([(0.0,), (1.0,)])
    def test_jitter_stays_within_backoff_bounds(self, fraction: float) -> None:
        self.limit.retry_jitter = True
        self.limit.retry_timeout = 15.0
        self.limit.redis_client.eval.side_effect = [0] * 10 + [1]
        with patch.object(random, "uniform", side_effect=lambda low, high: low + fraction * (high - low)):
            with self.limit.run(task_id="waiting"):
                pass
        for attempt, duration in enumerate(self.sleeps, start=1):
            backoff = min(0.1 * attempt**1.5, 1.714)
            self.assertGreaterEqual(duration, backoff / 2)
            self.assertLessEqual(duration, backoff)

    def test_failed_work_releases_acquired_slot(self) -> None:
        self.limit.retry_jitter = True
        self.limit.redis_client.eval.side_effect = [0, 1]
        with self.assertRaisesRegex(ValueError, "failed work"):
            with self.limit.run(task_id="waiting"):
                raise ValueError("failed work")
        self.limit.redis_client.zrem.assert_called_once_with("retry-timing", "waiting")

    def test_no_retry_fails_without_sleeping(self) -> None:
        self.limit.retry = None
        self.limit.retry_jitter = True
        self.limit.redis_client.eval.return_value = 0
        with self.assertRaises(ConcurrencyLimitExceeded):
            self.limit.use(task_id="waiting")
        self.assertEqual(self.sleeps, [])
        self.limit.redis_client.zrem.assert_not_called()

    def test_redis_failure_does_not_run_work(self) -> None:
        self.limit.retry_jitter = True
        self.limit.redis_client.eval.side_effect = [0, ConnectionError("redis unavailable")]
        work = Mock()
        with self.assertRaisesRegex(ConnectionError, "redis unavailable"):
            with self.limit.run(task_id="waiting"):
                work()
        work.assert_not_called()
        self.limit.redis_client.zrem.assert_not_called()

    @parameterized.expand(
        [
            (get_api_team_rate_limiter, 0.1005),
            (get_materialized_endpoints_rate_limiter, 0.134),
        ]
    )
    def test_factory_retry_policy(self, factory: Callable[[], RateLimit], expected_wait: float) -> None:
        limiter = replace(factory(), get_time=lambda: self.now, sleep=self.advance, allow_team_bypass=False)
        limiter.redis_client = Mock()
        limiter.redis_client.eval.side_effect = [0, 1]
        with patch.object(random, "uniform", side_effect=lambda low, high: (low + high) / 2):
            slot = limiter.use(task_id="waiting")
        self.assertIsNotNone(slot)
        self.assertAlmostEqual(sum(self.sleeps), expected_wait)
