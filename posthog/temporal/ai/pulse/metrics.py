"""Prometheus counters for the Pulse pipeline. No-op outside Temporal context."""

from temporalio import activity, workflow
from temporalio.common import MetricMeter

Attributes = dict[str, str | int | float | bool]


def _meter(attributes: Attributes | None = None) -> MetricMeter | None:
    """Return the active meter, or None when called outside a workflow/activity."""
    if activity.in_activity():
        meter = activity.metric_meter()
    elif workflow.in_workflow():
        meter = workflow.metric_meter()
    else:
        return None
    return meter.with_additional_attributes(attributes) if attributes else meter


def increment_dispatch_outcome(outcome: str, *, count: int = 1) -> None:
    """Dispatcher counters: eligible / dispatched / failed."""
    meter = _meter({"outcome": outcome})
    if meter is None:
        return
    meter.create_counter("pulse_dispatch_outcome", "Pulse dispatcher team outcomes").add(count)


def increment_scan_outcome(outcome: str, *, count: int = 1) -> None:
    """Per-team scan counters: delivered / failed."""
    meter = _meter({"outcome": outcome})
    if meter is None:
        return
    meter.create_counter("pulse_scan_outcome", "Pulse scan delivery outcomes").add(count)


def record_finding_count(count: int) -> None:
    """Number of findings persisted in a delivered digest."""
    meter = _meter()
    if meter is None:
        return
    meter.create_counter("pulse_finding_count", "Findings persisted per delivered digest").add(count)
