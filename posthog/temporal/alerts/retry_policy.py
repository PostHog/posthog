import datetime as dt
import dataclasses

from temporalio.common import RetryPolicy

from posthog.schema_enums import AlertCalculationInterval

from products.exports.backend.tasks.failure_handler import USER_QUERY_ERROR_NAMES

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


# Each activity's retry budget must exhaust inside workflow_execution: a server-side
# workflow timeout skips workflow code entirely, so the SLO completion would never be
# emitted and the alert's next_check_at would never advance. Compound worst cases
# (e.g. a slow prepare pushing evaluate past the envelope) can still hit the
# server-side timeout; activity_schedule_to_close guarantees no single activity does.
@dataclasses.dataclass(frozen=True)
class AlertTimeouts:
    workflow_execution: dt.timedelta
    activity_schedule_to_close: dt.timedelta
    evaluate_start_to_close: dt.timedelta
    evaluate_retry_policy: RetryPolicy
    heartbeat_timeout: dt.timedelta
    notify_start_to_close: dt.timedelta


_DEFAULT_TIMEOUTS = AlertTimeouts(
    workflow_execution=dt.timedelta(minutes=15),
    activity_schedule_to_close=dt.timedelta(minutes=12),
    evaluate_start_to_close=dt.timedelta(minutes=10),
    evaluate_retry_policy=ALERT_EVALUATE_RETRY_POLICY,
    heartbeat_timeout=dt.timedelta(minutes=2),
    notify_start_to_close=dt.timedelta(minutes=5),
)

_REAL_TIME_EVALUATE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_attempts=2,
    non_retryable_error_types=list(USER_QUERY_ERROR_NAMES),
)

_REAL_TIME_TIMEOUTS = AlertTimeouts(
    workflow_execution=dt.timedelta(minutes=8),
    activity_schedule_to_close=dt.timedelta(minutes=7),
    evaluate_start_to_close=dt.timedelta(minutes=3),
    evaluate_retry_policy=_REAL_TIME_EVALUATE_RETRY_POLICY,
    heartbeat_timeout=dt.timedelta(seconds=90),
    notify_start_to_close=dt.timedelta(seconds=60),
)


def alert_timeouts(calculation_interval: str | AlertCalculationInterval | None) -> AlertTimeouts:
    if calculation_interval == AlertCalculationInterval.REAL_TIME:
        return _REAL_TIME_TIMEOUTS
    return _DEFAULT_TIMEOUTS
