import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
import time_machine

from temporalio.common import RetryPolicy
from temporalio.testing import ActivityEnvironment

from posthog.temporal.ai_observability.retries import is_last_attempt

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCHEDULE_TO_CLOSE = timedelta(seconds=600)
POLICY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10), backoff_coefficient=2.0)
UNLIMITED_POLICY = RetryPolicy(maximum_attempts=0, initial_interval=timedelta(seconds=10))


@pytest.mark.parametrize(
    "attempt, policy, seconds_to_deadline, next_retry_delay, expected",
    [
        pytest.param(3, POLICY, 600, None, True, id="last_attempt_by_count"),
        pytest.param(1, POLICY, 600, timedelta(seconds=30), False, id="deadline_far_away"),
        pytest.param(1, POLICY, 10, timedelta(seconds=30), True, id="delay_lands_past_deadline"),
        pytest.param(2, POLICY, 15, None, True, id="policy_backoff_lands_past_deadline"),
        pytest.param(2, POLICY, 25, None, False, id="policy_backoff_lands_before_deadline"),
        pytest.param(1, UNLIMITED_POLICY, 600, None, True, id="unlimited_policy"),
    ],
)
def test_is_last_attempt(
    attempt: int,
    policy: RetryPolicy,
    seconds_to_deadline: float,
    next_retry_delay: timedelta | None,
    expected: bool,
) -> None:
    env = ActivityEnvironment()
    env.info = dataclasses.replace(
        env.info,
        attempt=attempt,
        retry_policy=policy,
        schedule_to_close_timeout=SCHEDULE_TO_CLOSE,
        scheduled_time=NOW - SCHEDULE_TO_CLOSE + timedelta(seconds=seconds_to_deadline),
    )

    with time_machine.travel(NOW, tick=False):
        assert env.run(is_last_attempt, next_retry_delay) is expected
