from datetime import UTC, datetime, timedelta

import temporalio.activity
from temporalio.common import RetryPolicy


def is_last_attempt(next_retry_delay: timedelta | None = None) -> bool:
    """Whether Temporal will not retry the running activity attempt if it fails.

    Retries end when the attempt count reaches the policy's maximum, or when the delay before the next
    attempt lands past the activity's schedule-to-close deadline. The delay defaults to the policy's own
    backoff; pass it when the activity raises with an explicit `next_retry_delay`. A missing or unlimited
    policy counts as last, so its failures stay reported.
    """
    if not temporalio.activity.in_activity():
        return True
    info = temporalio.activity.info()
    policy = info.retry_policy
    if policy is None or not policy.maximum_attempts or info.attempt >= policy.maximum_attempts:
        return True
    if info.schedule_to_close_timeout is None:
        return False
    delay = next_retry_delay or _policy_backoff(policy, info.attempt)
    return datetime.now(UTC) + delay > info.scheduled_time + info.schedule_to_close_timeout


def _policy_backoff(policy: RetryPolicy, attempt: int) -> timedelta:
    delay = policy.initial_interval * policy.backoff_coefficient ** (attempt - 1)
    return min(delay, policy.maximum_interval) if policy.maximum_interval else delay
