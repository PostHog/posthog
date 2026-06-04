from datetime import timedelta

from temporalio.common import RetryPolicy

from products.exports.backend.tasks.failure_handler import NON_RETRYABLE_SYSTEM_ERROR_NAMES, USER_QUERY_ERROR_NAMES

EXPORT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=10,
    # User errors never retry; non-retryable system errors (e.g. a browserless 429) are
    # excluded here too so retries can't compound an upstream rate-limit. The activity also
    # sets non_retryable=True on these, so this is belt-and-suspenders.
    non_retryable_error_types=[
        *list(USER_QUERY_ERROR_NAMES),
        *list(NON_RETRYABLE_SYSTEM_ERROR_NAMES),
    ],
)
