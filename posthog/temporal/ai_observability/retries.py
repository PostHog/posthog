import temporalio.activity
from temporalio.common import RetryPolicy


def is_last_attempt(retry_policy: RetryPolicy) -> bool:
    """Whether the running activity attempt is the final one `retry_policy` allows.

    The caller must pass the policy the workflow schedules the activity with. An unlimited policy
    (`maximum_attempts=0`) never reaches a last attempt by count, so every attempt counts as last
    and stays reportable. Outside an activity there is no retry, so the call counts as last too.
    """
    if not temporalio.activity.in_activity() or not retry_policy.maximum_attempts:
        return True
    return temporalio.activity.info().attempt >= retry_policy.maximum_attempts
