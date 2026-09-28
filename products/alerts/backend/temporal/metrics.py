"""Prometheus metrics for the shared alerts platform's evaluation path.

Emitted through Temporal's own meter, so a counter carries the worker, queue and activity
attributes the runtime already attaches, and the worker's bucket overrides reach the histograms
below. Every call site wraps these in `safe_record`: a metric must never fail a check.
"""

import datetime as dt

from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.common.metrics import get_metric_meter

logger = get_write_only_logger(__name__)

# Consumed by `posthog/temporal/common/worker.py` to override Prometheus default buckets.
# Keep in sync with the histograms below.
ALERTS_PLATFORM_LATENCY_HISTOGRAM_METRICS = (
    "alerts_platform_batch_duration_ms",
    "alerts_platform_scheduler_lag_ms",
)

ALERTS_PLATFORM_LATENCY_HISTOGRAM_BUCKETS = [
    100.0,
    500.0,
    1_000.0,
    5_000.0,
    10_000.0,
    30_000.0,
    60_000.0,
    120_000.0,
    300_000.0,
    600_000.0,
]


def safe_record(fn, *args, **kwargs) -> None:
    """Best-effort metric recording. A batch that decided correctly must not fail on telemetry."""
    try:
        fn(*args, **kwargs)
    except Exception as error:
        logger.warning("alerts_platform_metric_failed", metric=fn.__name__, error=str(error))


def increment_checks(source: str, outcome: str) -> None:
    get_metric_meter({"source": source, "outcome": outcome}).create_counter(
        "alerts_platform_checks_total",
        "Checks the shared platform decided, by source and notification outcome",
    ).add(1)


def increment_state_transition(source: str, from_state: str, to_state: str) -> None:
    get_metric_meter({"source": source, "from": from_state, "to": to_state}).create_counter(
        "alerts_platform_state_transitions_total",
        "Alert state transitions the shared platform decided",
    ).add(1)


def increment_deliveries_deferred(source: str, count: int) -> None:
    """Deliveries a batch decided on but could not carry inside its activity payload bound.

    They keep their due time, so this counts work a later tick repeats rather than work lost.
    """
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_deliveries_deferred_total",
        "Deliveries left out of a batch by its payload bound; the alerts stay due",
    ).add(count)


def increment_deliveries_previewed(source: str) -> None:
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_deliveries_previewed_total",
        "Deliveries recorded as a preview instead of being sent",
    ).add(1)


def increment_outcomes_recorded(count: int) -> None:
    get_metric_meter().create_counter(
        "alerts_platform_outcomes_recorded_total",
        "Check decisions written to the shared alert tables",
    ).add(count)


def record_batch_duration(source: str, duration_ms: int) -> None:
    get_metric_meter({"source": source}).create_histogram_timedelta(
        name="alerts_platform_batch_duration_ms",
        description="Wall time for one batch key's evaluation, queries included",
        unit="ms",
    ).record(dt.timedelta(milliseconds=duration_ms))


def record_scheduler_lag(source: str, lag_ms: int) -> None:
    """How far past its due time a check was evaluated. Rising lag means discovery's bound is
    biting, because a key it omits grows more overdue until a later tick takes it."""
    get_metric_meter({"source": source}).create_histogram_timedelta(
        name="alerts_platform_scheduler_lag_ms",
        description="Delay between a check's due time and the evaluation that took it",
        unit="ms",
    ).record(dt.timedelta(milliseconds=lag_ms))
