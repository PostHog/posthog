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


@dataclasses.dataclass(frozen=True)
class AlertTimeouts:
    workflow_execution: dt.timedelta
    activity_schedule_to_close: dt.timedelta
    evaluate_start_to_close: dt.timedelta
    evaluate_retry_policy: RetryPolicy
    notify_start_to_close: dt.timedelta


_DEFAULT_TIMEOUTS = AlertTimeouts(
    workflow_execution=dt.timedelta(minutes=15),
    activity_schedule_to_close=dt.timedelta(minutes=12),
    evaluate_start_to_close=dt.timedelta(minutes=10),
    evaluate_retry_policy=ALERT_EVALUATE_RETRY_POLICY,
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
    workflow_execution=dt.timedelta(minutes=7),
    activity_schedule_to_close=dt.timedelta(minutes=6),
    evaluate_start_to_close=dt.timedelta(minutes=3),
    evaluate_retry_policy=_REAL_TIME_EVALUATE_RETRY_POLICY,
    notify_start_to_close=dt.timedelta(seconds=60),
)


def alert_timeouts(calculation_interval: str | AlertCalculationInterval | None) -> AlertTimeouts:
    if calculation_interval == AlertCalculationInterval.REAL_TIME:
        return _REAL_TIME_TIMEOUTS
    return _DEFAULT_TIMEOUTS
