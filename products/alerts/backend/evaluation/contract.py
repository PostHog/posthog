from dataclasses import dataclass
from typing import Protocol

from posthog.schema import AlertCondition, AlertConditionType, IntervalType

from posthog.api.services.query import ExecutionMode

from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


@dataclass
class SeriesPoint:
    date: str | None  # None for non-time-series (single aggregated value)
    value: float | None  # None = missing data point this interval


@dataclass
class ComparableSeries:
    label: str  # series / breakdown label, used in breach messages
    points: list[SeriesPoint]  # chronologically ascending; extractor guarantees order
    current_index: int  # comparison anchor; previous = current_index - 1
    is_current_interval: bool = False  # anchor is the ongoing (incomplete) interval — affects breach wording


@dataclass
class ExtractionResult:
    """Everything the comparator needs from an extractor, so the dispatcher stays kind-agnostic.

    ``subject`` and ``framed`` shape the breach message: framed trends messages read
    "The insight value (label) for previous day (...)"; unframed messages (e.g. SQL insights,
    which have no series label or interval) read "The SQL insight value (...)".
    """

    series: list[ComparableSeries]
    is_breakdown: bool = False  # breakdown queries report no single no-breach value
    interval_type: IntervalType | None = None  # breach-message interval framing (time-series trends only)
    subject: str = "The insight value"  # breach-message subject
    framed: bool = True  # include the "(label) for current/previous interval" framing
    unit: str = ""  # appended to breach-message values (e.g. "%" for funnel conversion rates)
    # Detector-path-only: True means the query returned zero rows, so the metric is genuinely 0. An
    # empty ``series`` with this False instead means rows existed but none were long enough to score —
    # the detector reports that as an uncomputed value (None). Threshold extractors never set this
    # (they emit a zero sentinel series) and the comparator ignores it.
    empty_query_result: bool = False
    # When True, every breaching series is reported (capped) instead of stopping at the first —
    # any-row SQL alerts use this so the notification names all violating rows. Trends breakdowns
    # keep first-breach-only for parity with their historical messages.
    aggregate_breaches: bool = False


def zero_sentinel_series() -> ComparableSeries:
    """The shared empty-result sentinel: two zero points so relative conditions compute
    0 - 0 = 0 rather than skipping for lack of a previous point; absolute reads 0 at the anchor."""
    return ComparableSeries(
        label="empty result",
        points=[SeriesPoint(date=None, value=0.0), SeriesPoint(date=None, value=0.0)],
        current_index=1,
    )


class AlertExtractionError(Exception):
    """The alert cannot be evaluated as configured (wrong query shape, bad config).

    Routed to the errored-alert notification path — distinct from "evaluated fine,
    no data this interval", which is represented as SeriesPoint(value=None).
    """


def lookback_intervals_for(condition: AlertCondition) -> int:
    """How many trailing intervals an extractor must fetch for this condition.

    Absolute needs the current + previous interval (2); relative needs three intervals
    because, when the current interval is still accumulating, it compares the previous
    interval against the one before it.
    """
    match condition.type:
        case AlertConditionType.ABSOLUTE_VALUE:
            return 2
        case AlertConditionType.RELATIVE_INCREASE | AlertConditionType.RELATIVE_DECREASE:
            return 3
        case _:
            raise AlertExtractionError(f"Unsupported alert condition type: {condition.type}")


def execution_mode_for_alert(interval: IntervalType | None, *, high_frequency: bool) -> ExecutionMode:
    """Pick the query execution mode for an alert check, shared by every extractor.

    Skip the recent-results cache and recompute synchronously when the data moves faster than the
    cache key can track: hourly-bucketed insights (the key uses relative times like ``-2h``) or an
    every-15-minutes alert cadence. Otherwise reuse a recent cached result, recomputing only if stale.
    """
    if interval == IntervalType.HOUR or high_frequency:
        return ExecutionMode.CALCULATE_BLOCKING_ALWAYS
    return ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE


class Extractor(Protocol):
    def extract(self, alert: AlertConfiguration, insight: Insight, query: object) -> ExtractionResult: ...
