"""The seam that lets one APM alert span logs, traces, and metrics.

An APM alert names one signal and one threshold. Producing the number is signal-specific —
a log count, a span error rate, a metric value — but everything after that point is not, so
the shared lifecycle in `products/alerts/backend/state_machine.py` receives the same
`CheckInput` whichever signal produced it. That is what makes the three alertable as one
object rather than three parallel alert products.

Deliberately free of Django and ClickHouse: the comparison is the part worth testing in
isolation, and it stays testable without either.
"""

from __future__ import annotations

from enum import StrEnum

from posthog.dataclasses import frozen

from products.alerts.backend.state_machine import CheckInput


class ApmSignalKind(StrEnum):
    LOGS = "logs"
    TRACES = "traces"
    METRICS = "metrics"


class ThresholdOperator(StrEnum):
    ABOVE = "above"
    BELOW = "below"


@frozen
class SignalMeasurement:
    """One evaluation window reduced to a single number.

    `value` is None when the window reached no verdict — no matching rows, or no samples in
    the interval. That is not the same as a measured zero, and the two must not collapse.
    """

    kind: ApmSignalKind
    value: float | None


def evaluate_threshold(measurement: SignalMeasurement, *, threshold: float, operator: ThresholdOperator) -> CheckInput:
    """Compare one measurement against the alert's threshold."""
    if measurement.value is None:
        # Reporting "not breached" here would resolve a firing alert on an ingestion gap, and
        # reporting a breach would fire every `below` alert during one. Inconclusive leaves
        # both the state and the failure counter untouched.
        return CheckInput(threshold_breached=False, is_inconclusive=True)

    if operator is ThresholdOperator.ABOVE:
        breached = measurement.value > threshold
    else:
        breached = measurement.value < threshold

    return CheckInput(threshold_breached=breached)
