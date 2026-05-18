from typing import Any

from posthog.schema import AlertCondition, AlertConditionType, HogQLQuery, InsightThreshold, InsightThresholdType

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models import AlertConfiguration, Insight
from posthog.tasks.alerts.utils import AlertEvaluationResult, compute_relative_change, format_threshold_breach

_HOGQL_SUBJECT = "The SQL insight value"


def check_hogql_alert(alert: AlertConfiguration, insight: Insight, query: HogQLQuery) -> AlertEvaluationResult:
    condition = AlertCondition.model_validate(alert.condition)
    threshold = InsightThreshold.model_validate(alert.threshold.configuration) if alert.threshold else None

    if not threshold or not threshold.bounds:
        return AlertEvaluationResult(value=0, breaches=[])

    calculation_result = calculate_for_query_based_insight(
        insight,
        team=alert.team,
        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user=None,
    )

    values = _extract_trailing_column_values(calculation_result.result)

    match condition.type:
        case AlertConditionType.ABSOLUTE_VALUE:
            if threshold.type != InsightThresholdType.ABSOLUTE:
                raise ValueError("Absolute threshold not configured for alert condition ABSOLUTE_VALUE")

            current = values[-1]
            breaches = format_threshold_breach(
                threshold.bounds, current, threshold.type, condition.type, subject=_HOGQL_SUBJECT
            )
            return AlertEvaluationResult(value=current, breaches=breaches)

        case AlertConditionType.RELATIVE_INCREASE | AlertConditionType.RELATIVE_DECREASE:
            if len(values) < 2:
                raise ValueError(
                    "Relative alerts on HogQL insights need at least two rows (current and previous), "
                    "ordered chronologically."
                )

            change = compute_relative_change(condition.type, threshold.type, values[-1], values[-2])
            breaches = format_threshold_breach(
                threshold.bounds, change, threshold.type, condition.type, subject=_HOGQL_SUBJECT
            )
            return AlertEvaluationResult(value=change, breaches=breaches)

        case _:
            raise NotImplementedError(f"Unsupported alert condition type: {condition.type}")


def _extract_trailing_column_values(rows: Any) -> list[float]:
    """Extracts the last two rows of a HogQL response as a list of floats.

    Only the tail is inspected — alert evaluation never reads further back than the second-to-last
    row, so validating earlier rows would waste work on data we won't use.
    """
    if rows is None or not isinstance(rows, list) or len(rows) == 0:
        raise ValueError("HogQL alert query returned no rows.")

    tail = rows[-2:]
    # Position labels keep error messages meaningful regardless of how many rows the query returned.
    positions = ["second-to-last row", "last row"] if len(tail) == 2 else ["last row"]
    values: list[float] = []
    for position, row in zip(positions, tail):
        if not isinstance(row, list | tuple):
            raise ValueError(
                f"HogQL alert query must return rows as lists/tuples (got {type(row).__name__} for the {position})."
            )
        if len(row) != 1:
            raise ValueError(
                f"HogQL alert query must return exactly one column (got {len(row)} columns for the {position})."
            )

        raw = row[0]
        if raw is None:
            # None buckets are treated as 0 to match trends-alert handling of empty intervals.
            values.append(0.0)
            continue
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError(
                f"HogQL alert query must return a numeric column (got {type(raw).__name__} for the {position})."
            )
        values.append(float(raw))

    return values
