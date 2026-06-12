from dataclasses import dataclass
from typing import Protocol

from posthog.schema import AlertCondition, AlertConditionType, IntervalType

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
    # Detector path only: the query returned zero rows, so the metric is genuinely 0. An empty
    # ``series`` with this False instead means rows existed but none were long enough to score —
    # the detector reports that as an uncomputed value (None). Threshold extractors never set this
    # (they emit a zero sentinel series) and the comparator ignores it.
    empty_query_result: bool = False


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


class Extractor(Protocol):
    def extract(self, alert: AlertConfiguration, insight: Insight, query: object) -> ExtractionResult: ...
