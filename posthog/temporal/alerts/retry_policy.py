import datetime as dt

from temporalio.common import RetryPolicy

from posthog.tasks.exports.failure_handler import USER_QUERY_ERROR_NAMES

ALERT_PREPARE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)

ALERT_EVALUATE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=5,
    non_retryable_error_types=list(USER_QUERY_ERROR_NAMES),
)

ALERT_NOTIFY_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    maximum_interval=dt.timedelta(minutes=2),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)
