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

# Calibrated 2026-07-02 against slo_operation_completed (alert_check, prod, last 7d, n=884k):
# p50=2.1s  p95=10.1s  p99=23.3s  max=358.8s (~6 min)
# workflow_execution gives ~1 min headroom over observed max;
# evaluate_start_to_close covers p99 with room for the 2-retry budget.
_REAL_TIME_TIMEOUTS = AlertTimeouts(
    workflow_execution=dt.timedelta(minutes=7),
    activity_schedule_to_close=dt.timedelta(minutes=6),
    evaluate_start_to_close=dt.timedelta(minutes=3),
    evaluate_retry_policy=_REAL_TIME_EVALUATE_RETRY_POLICY,
    heartbeat_timeout=dt.timedelta(seconds=90),
    notify_start_to_close=dt.timedelta(seconds=60),
)


def alert_timeouts(calculation_interval: str | AlertCalculationInterval | None) -> AlertTimeouts:
    if calculation_interval == AlertCalculationInterval.REAL_TIME:
        return _REAL_TIME_TIMEOUTS
    return _DEFAULT_TIMEOUTS
