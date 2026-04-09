import datetime as dt

from temporalio.common import RetryPolicy

# Replaces the @retry(retry_if_exception_type(CH_TRANSIENT_ERRORS), ...)
# tenacity decorator currently on `check_alert` in
# posthog/tasks/alerts/checks.py:217-227. Same intent: retry on transient
# ClickHouse errors with exponential backoff.
#
# Permanent errors (validation, deleted insight) are caught inside the
# evaluate activity and returned as a result rather than raised, so they
# don't trigger retries here. Anything that DOES escape is treated as
# transient by default — `non_retryable_error_types` is intentionally empty.
ALERT_EVALUATE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_attempts=4,
    non_retryable_error_types=[],
)

# Notification retries are independent of evaluate retries — this is the
# TODO win from posthog/tasks/alerts/checks.py:338. SMTP/Slack flakes get
# their own backoff without re-running the CH query.
ALERT_NOTIFY_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    maximum_interval=dt.timedelta(minutes=2),
    backoff_coefficient=2.0,
    maximum_attempts=5,
    non_retryable_error_types=[],
)
