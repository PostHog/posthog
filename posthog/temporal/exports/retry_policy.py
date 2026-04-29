from datetime import timedelta

from temporalio.common import RetryPolicy

from posthog.tasks.exports.failure_handler import USER_QUERY_ERROR_NAMES

EXPORT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=10,
    non_retryable_error_types=[
        *list(USER_QUERY_ERROR_NAMES),
    ],
)
