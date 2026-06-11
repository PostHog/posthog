import math
from decimal import Decimal
from typing import Any

from posthog.schema import AlertCondition, AlertConditionType

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import EventSource

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight

_HOGQL_SUBJECT = "The SQL insight value"


class HogQLExtractor:
    """Normalize a HogQL/SQL-backed insight into a single ``ComparableSeries``.

    A HogQL alert assumes the query returns a single numeric column, chronologically ordered by
    the query itself — the evaluator trusts the query's ORDER BY and treats the last row as the
    current value (there is no incomplete-interval policy to apply). The shared comparator then
    interprets it exactly as it does a trend.
    """

    def extract(self, alert: AlertConfiguration, insight: Insight, query: Any) -> ExtractionResult:
        condition = AlertCondition.model_validate(alert.condition)

        calculation_result = calculate_for_query_based_insight(
            insight,
            team=alert.team,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=None,
            analytics_props={"source": EventSource.ALERT},
        )
        values = _extract_trailing_column_values(calculation_result.result, alert)

        is_relative = condition.type in (AlertConditionType.RELATIVE_INCREASE, AlertConditionType.RELATIVE_DECREASE)
        if is_relative and len(values) < 2:
            raise AlertExtractionError(
                "Relative alerts on SQL insights need at least two rows (current and previous), "
                "ordered chronologically."
            )

        points = [SeriesPoint(date=None, value=v) for v in values]
        series = ComparableSeries(label="result", points=points, current_index=len(points) - 1)
        return ExtractionResult(series=[series], is_breakdown=False, subject=_HOGQL_SUBJECT, framed=False)


def _extract_trailing_column_values(rows: Any, alert: AlertConfiguration) -> list[float]:
    """Extract the last two rows of a HogQL response as floats.

    Only the tail is inspected — alert evaluation never reads further back than the second-to-last
    row, so validating earlier rows would waste work on data we won't use. ``None`` buckets become
    0 to match the trends-alert handling of empty intervals.
    """
    # ``None`` (vs an empty list) means the query layer swallowed an error — raise to avoid a
    # misfire, matching the trends extractor's handling of a None result.
    if rows is None:
        raise RuntimeError(f"No results found for insight with alert id = {alert.id}")
    if not isinstance(rows, list):
        raise AlertExtractionError(f"SQL alert query returned an unexpected result shape ({type(rows).__name__}).")
    if len(rows) == 0:
        raise AlertExtractionError("SQL alert query returned no rows.")

    tail = rows[-2:]
    positions = ["second-to-last row", "last row"] if len(tail) == 2 else ["last row"]
    values: list[float] = []
    for position, row in zip(positions, tail):
        if not isinstance(row, list | tuple):
            raise AlertExtractionError(
                f"SQL alert query must return rows as lists/tuples (got {type(row).__name__} for the {position})."
            )
        if len(row) != 1:
            raise AlertExtractionError(
                f"SQL alert query must return exactly one column (got {len(row)} columns for the {position})."
            )

        raw = row[0]
        if raw is None:
            values.append(0.0)
            continue
        # ClickHouse Decimal columns surface as decimal.Decimal; accept them alongside int/float.
        if isinstance(raw, bool) or not isinstance(raw, int | float | Decimal):
            raise AlertExtractionError(
                f"SQL alert query must return a numeric column (got {type(raw).__name__} for the {position})."
            )
        value = float(raw)
        if not math.isfinite(value):
            raise AlertExtractionError(
                f"SQL alert query must return a finite numeric value (got {raw} for the {position})."
            )
        values.append(value)

    return values
