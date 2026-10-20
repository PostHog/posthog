import datetime as dt
import dataclasses

from temporalio.common import RetryPolicy

from posthog.schema_enums import AlertCalculationInterval

from products.exports.backend.tasks.failure_handler import USER_QUERY_ERROR_NAMES

# A user's query error won't clear on retry, so evaluate_alert fails fast on it. Temporal matches
# non-retryable types by exact name, so transient cluster memory pressure — a distinct subclass
# name — stays retryable without being listed here. Sorted for a stable order across processes.
_EVALUATE_NON_RETRYABLE_ERROR_NAMES = sorted(USER_QUERY_ERROR_NAMES)

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
    non_retryable_error_types=_EVALUATE_NON_RETRYABLE_ERROR_NAMES,
)

ALERT_NOTIFY_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    maximum_interval=dt.timedelta(minutes=2),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)


@dataclasses.dataclass(frozen=True)
class SlotLease:
    """How a running evaluation keeps its admission slot: re-held every `refresh`, lapsing after `lease`."""

    lease: dt.timedelta
    refresh: dt.timedelta


# A worker that dies stops refreshing, and Temporal retries its check heartbeat_timeout after the
# last heartbeat. The slot must still be held when that retry takes it over, or the scheduler fills
# it in between and the retry runs past the limit. The last refresh can be a whole interval before
# the death, so the grace must cover that interval plus Temporal's retry backoff and pickup delay.
_SLOT_REFRESH_INTERVAL = dt.timedelta(seconds=30)
_SLOT_TAKEOVER_GRACE = dt.timedelta(minutes=2)


@dataclasses.dataclass(frozen=True)
class AlertTimeouts:
    """Every clock on a check, derived from one evaluation budget per cadence.

    Build one with for_budget. Evaluate's per-attempt timeout equals its total budget, so Temporal
    never restarts an attempt that is still heartbeating: a lost heartbeat is the only thing that
    retries a running check. The budget ends by cancelling the attempt, which stops its query.
    """

    workflow_execution: dt.timedelta
    activity_schedule_to_close: dt.timedelta
    evaluate_start_to_close: dt.timedelta
    evaluate_retry_policy: RetryPolicy
    heartbeat_timeout: dt.timedelta
    prepare_start_to_close: dt.timedelta
    notify_start_to_close: dt.timedelta
    evaluation_slot_lease: SlotLease

    @classmethod
    def for_budget(
        cls,
        *,
        evaluate: dt.timedelta,
        heartbeat: dt.timedelta,
        prepare: dt.timedelta,
        notify: dt.timedelta,
        evaluate_retry_policy: RetryPolicy,
    ) -> "AlertTimeouts":
        return cls(
            workflow_execution=prepare + evaluate + notify,
            activity_schedule_to_close=evaluate,
            evaluate_start_to_close=evaluate,
            evaluate_retry_policy=evaluate_retry_policy,
            heartbeat_timeout=heartbeat,
            prepare_start_to_close=prepare,
            notify_start_to_close=notify,
            evaluation_slot_lease=SlotLease(lease=heartbeat + _SLOT_TAKEOVER_GRACE, refresh=_SLOT_REFRESH_INTERVAL),
        )


_DEFAULT_TIMEOUTS = AlertTimeouts.for_budget(
    evaluate=dt.timedelta(minutes=12),
    heartbeat=dt.timedelta(minutes=2),
    prepare=dt.timedelta(minutes=2),
    notify=dt.timedelta(minutes=5),
    evaluate_retry_policy=ALERT_EVALUATE_RETRY_POLICY,
)

_REAL_TIME_EVALUATE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_attempts=2,
    non_retryable_error_types=_EVALUATE_NON_RETRYABLE_ERROR_NAMES,
)

_REAL_TIME_TIMEOUTS = AlertTimeouts.for_budget(
    evaluate=dt.timedelta(minutes=7),
    heartbeat=dt.timedelta(seconds=90),
    prepare=dt.timedelta(minutes=2),
    notify=dt.timedelta(seconds=60),
    evaluate_retry_policy=_REAL_TIME_EVALUATE_RETRY_POLICY,
)


def alert_timeouts(calculation_interval: str | AlertCalculationInterval | None) -> AlertTimeouts:
    if calculation_interval == AlertCalculationInterval.REAL_TIME:
        return _REAL_TIME_TIMEOUTS
    return _DEFAULT_TIMEOUTS
