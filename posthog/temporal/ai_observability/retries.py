from datetime import UTC, datetime, timedelta

import temporalio.activity


def is_last_attempt(next_retry_delay: timedelta | None = None) -> bool:
    """Whether Temporal will not retry the running activity attempt if it fails.

    The count check reads the retry policy the server applies to this activity. A missing or
    unlimited policy (`maximum_attempts=0`) never ends retries by count. When the caller passes the
    delay before the next attempt, the attempt is also last if that delay lands past the activity's
    schedule-to-close deadline, because Temporal then schedules no further attempt. Outside an
    activity there is no retry, so the call counts as last.
    """
    if not temporalio.activity.in_activity():
        return True
    info = temporalio.activity.info()
    policy = info.retry_policy
    if policy is not None and policy.maximum_attempts and info.attempt >= policy.maximum_attempts:
        return True
    if next_retry_delay is None or info.schedule_to_close_timeout is None:
        return False
    deadline = info.scheduled_time + info.schedule_to_close_timeout
    return datetime.now(UTC) + next_retry_delay > deadline
