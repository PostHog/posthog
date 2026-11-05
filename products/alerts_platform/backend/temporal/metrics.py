"""Prometheus metrics for the shared alerts platform's evaluation path.

Emitted through Temporal's own meter, so a counter carries the worker, queue and activity
attributes the runtime already attaches, and the worker's bucket overrides reach the histograms
below. Every call site wraps these in `safe_record`: a metric must never fail a check.
"""

import datetime as dt
from collections.abc import Callable
from functools import cache
from typing import Literal

from prometheus_client import Counter, Histogram

from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.common.metrics import Attributes, get_metric_meter

logger = get_write_only_logger(__name__)

# Consumed by `posthog/temporal/common/worker.py` to override Prometheus default buckets.
# Keep in sync with the histograms below.
ALERTS_PLATFORM_LATENCY_HISTOGRAM_METRICS = (
    "alerts_platform_batch_duration_ms",
    "alerts_platform_scheduler_lag_ms",
    "alerts_platform_delivery_lag_ms",
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


# A tick must end inside its minute, so these buckets resolve the seconds up to and past 60.
ALERTS_PLATFORM_TICK_HISTOGRAM_METRICS = (
    "alerts_platform_tick_duration_ms",
    "alerts_platform_tick_start_delay_ms",
)

ALERTS_PLATFORM_TICK_HISTOGRAM_BUCKETS = [
    100.0,
    500.0,
    1_000.0,
    2_000.0,
    5_000.0,
    10_000.0,
    15_000.0,
    20_000.0,
    30_000.0,
    40_000.0,
    50_000.0,
    60_000.0,
    90_000.0,
    120_000.0,
]

ALERTS_PLATFORM_TICK_KEYS_METRICS = ("alerts_platform_tick_keys",)

ALERTS_PLATFORM_TICK_KEYS_BUCKETS = [
    0.0,
    50.0,
    100.0,
    200.0,
    300.0,
    400.0,
    500.0,
    600.0,
    800.0,
    1_000.0,
    1_250.0,
    1_500.0,
    2_000.0,
    3_000.0,
    5_000.0,
]


def safe_record(fn: Callable[..., object], *args: object, **kwargs: object) -> None:
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


def increment_checks_skipped(source: str, reason: str) -> None:
    """Checks that reached an outcome without a query answering them.

    A rising reason means the platform is spending ticks on work it cannot do: a blocked window,
    a configuration no data satisfies, or a query that keeps failing.
    """
    get_metric_meter({"source": source, "reason": reason}).create_counter(
        "alerts_platform_checks_skipped_total",
        "Checks decided without an evaluation, by reason",
    ).add(1)


def increment_notifications_muted(source: str, reason: str) -> None:
    """Announcements a mute held back.

    The alert still transitioned, so this is the only signal that a person was not told. A
    rising count with no matching unmute announcement means mutes are swallowing alerts.
    """
    get_metric_meter({"source": source, "reason": reason}).create_counter(
        "alerts_platform_notifications_muted_total",
        "Announcements held by a mute, by reason",
    ).add(1)


def increment_history_rows_dropped(source: str, count: int) -> None:
    """Check rows the platform decided but could not record.

    The alert's state and schedule are already written when this rises, so the cost is a gap in
    history rather than a lost evaluation. A comparison against a source's own stack reads as a
    disagreement where the gap falls.
    """
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_history_rows_dropped_total",
        "Check history rows lost to a failed ClickHouse write",
    ).add(count)


def increment_state_transition(source: str, from_state: str, to_state: str) -> None:
    get_metric_meter({"source": source, "from": from_state, "to": to_state}).create_counter(
        "alerts_platform_state_transitions_total",
        "Alert state transitions the shared platform decided",
    ).add(1)


def increment_groups_over_cap(source: str, count: int) -> None:
    """Groups an outcome reported past its configuration's `max_instances`. A source admits groups
    before it reports them, so a nonzero count means a source skipped that step."""
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_groups_over_cap_total",
        "Groups dropped at record time because the configuration had no room for another instance",
    ).add(count)


def increment_instances_reaped(source: str, count: int) -> None:
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_instances_reaped_total",
        "Idle alert instances deleted so their configuration can admit new groups",
    ).add(count)


def increment_deliveries_deferred(source: str, count: int) -> None:
    """Deliveries a batch decided on but could not carry inside its activity payload bound.

    They keep their due time, so this counts work a later tick repeats rather than work lost.
    """
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_deliveries_deferred_total",
        "Deliveries left out of a batch by its payload bound; the alerts stay due",
    ).add(count)


def increment_discovery_omitted(source: str, count: int) -> None:
    """Batch keys a tick found due and left out under the source's discovery limit.

    They keep their due time, so a later tick takes them. A count that stays above zero means the
    limit is below the demand, and scheduler lag grows for that source.
    """
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_discovery_omitted_total",
        "Due batch keys a tick left out under the source's discovery limit; the alerts stay due",
    ).add(count)


def increment_checks_deferred(source: str, count: int) -> None:
    """Checks an evaluation pool turned away because it was full.

    They keep their due time, so this counts work a later tick repeats. A sustained count means the
    pool is the bottleneck rather than ClickHouse.
    """
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_checks_deferred_total",
        "Checks a full evaluation pool turned away; the alerts stay due",
    ).add(count)


def increment_checks_unfinished(source: str, count: int) -> None:
    """Admitted checks that reached no outcome, because their activity failed or timed out.

    They keep their due time, so a later tick repeats them. Unlike a skipped check, nothing
    records them anywhere else.
    """
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_checks_unfinished_total",
        "Admitted checks that reached no outcome; the alerts stay due",
    ).add(count)


def increment_describer_failures(source: str) -> None:
    """A source's describer raised, so its alerts went out in the platform's generic wording."""
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_describer_failures_total",
        "Messages sent in the platform's wording because the source's describer raised",
    ).add(1)


def increment_slack_renderer_failures(source: str) -> None:
    """A source's Slack renderer raised, so its alerts went out in the platform's generic layout."""
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_slack_renderer_failures_total",
        "Slack messages sent in the platform's layout because the source's renderer raised",
    ).add(1)


def increment_root_edit_failures(provider: str) -> None:
    """An opening message could not be brought up to date, so it shows an older state."""
    get_metric_meter({"provider": provider}).create_counter(
        "alerts_platform_root_edit_failures_total",
        "Opening messages left showing an older state because the edit failed",
    ).add(1)


def increment_deliveries_previewed(source: str) -> None:
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_deliveries_previewed_total",
        "Deliveries recorded as a preview instead of being sent",
    ).add(1)


def increment_holds_expired(source: str) -> None:
    """Held deliveries the safety net sent because nothing released them before their deadline.

    Each one is a source that held a delivery and never answered, so a rise means a stalled source.
    """
    get_metric_meter({"source": source}).create_counter(
        "alerts_platform_holds_expired_total",
        "Held deliveries the safety net sent after their deadline passed",
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


DeliveryOutcomeLabel = Literal["sent", "failed", "misconfigured", "already_delivered", "busy", "no_transport"]

_DELIVERIES_DESCRIPTION = "Transitions a delivery handled, by provider, delivery path and outcome"
_DELIVERY_LAG_DESCRIPTION = "Delay between the check that decided a transition and the send that announced it"


# A web process sends inline, outside any worker, when Temporal is unreachable or a deleted alert's
# resolve cannot wait. It has no Temporal meter, so it records the same series in its own registry.
# Created on first use, never at import: a worker exports this registry beside Temporal's meter, and
# the same family declared twice makes Prometheus reject the worker's whole scrape.
@cache
def _inline_deliveries() -> Counter:
    return Counter("alerts_platform_deliveries", _DELIVERIES_DESCRIPTION, ["source", "provider", "path", "outcome"])


@cache
def _inline_delivery_lag() -> Histogram:
    return Histogram(
        "alerts_platform_delivery_lag_ms",
        _DELIVERY_LAG_DESCRIPTION,
        ["source", "provider"],
        buckets=ALERTS_PLATFORM_LATENCY_HISTOGRAM_BUCKETS,
    )


def increment_deliveries(source: str, provider: str, path: str, outcome: DeliveryOutcomeLabel, count: int = 1) -> None:
    """What happened to each transition a delivery carried, per destination provider.

    `already_delivered` is a retry finding its send done, and `busy` a send that waits on another
    one holding the thread. Neither sent anything, so a rising `sent` with a flat `failed` is the
    only reading that says alerts reach people. `misconfigured` is a refusal only the destination's
    owner can fix, so it stays out of `failed`, which measures the platform.
    """
    labels: Attributes = {"source": source, "provider": provider, "path": path, "outcome": outcome}
    try:
        meter = get_metric_meter(labels)
    except RuntimeError:
        _inline_deliveries().labels(**labels).inc(count)
        return
    meter.create_counter("alerts_platform_deliveries_total", _DELIVERIES_DESCRIPTION).add(count)


def record_delivery_lag(source: str, provider: str, lag_ms: int) -> None:
    """How long after the check decided a transition its message went out. Evaluation metrics
    cannot see a delivery queue that stalls, so this is the one that does."""
    labels: Attributes = {"source": source, "provider": provider}
    try:
        meter = get_metric_meter(labels)
    except RuntimeError:
        _inline_delivery_lag().labels(**labels).observe(lag_ms)
        return
    meter.create_histogram_timedelta(
        name="alerts_platform_delivery_lag_ms", description=_DELIVERY_LAG_DESCRIPTION, unit="ms"
    ).record(dt.timedelta(milliseconds=lag_ms))


def record_tick_keys(keys: int) -> None:
    """Batch keys one tick's discovery found due, the ones its limits left out included. Called
    from workflow code; the workflow meter emits nothing during replay."""
    get_metric_meter().create_histogram(
        name=ALERTS_PLATFORM_TICK_KEYS_METRICS[0],
        description="Batch keys one tick's discovery found due, including those its limits left out",
    ).record(keys)


def record_tick_end(*, duration: dt.timedelta, deadline_reached: bool) -> None:
    """One finished tick, measured from its scheduled minute. A tick that runs past its minute
    makes the schedule skip the next one, so the duration's distance from 60 seconds is the
    headroom left. Called from workflow code; the workflow meter emits nothing during replay."""
    get_metric_meter({"deadline_reached": str(deadline_reached).lower()}).create_histogram_timedelta(
        name="alerts_platform_tick_duration_ms",
        description="Time from a tick's scheduled minute to the end of its last dispatch page",
        unit="ms",
    ).record(duration)


def record_scheduler_lag(source: str, lag_ms: int) -> None:
    """How far past its due time a check was evaluated. Rising lag means discovery's bound is
    biting, because a key it omits grows more overdue until a later tick takes it."""
    get_metric_meter({"source": source}).create_histogram_timedelta(
        name="alerts_platform_scheduler_lag_ms",
        description="Delay between a check's due time and the evaluation that took it",
        unit="ms",
    ).record(dt.timedelta(milliseconds=lag_ms))
