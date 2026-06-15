import math
from decimal import Decimal
from typing import Any

from posthog.schema import AlertCondition, AlertConditionType, HogQLAlertConfig, HogQLAlertEvaluation

from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import EventSource

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    zero_sentinel_series,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight

_HOGQL_SUBJECT = "The SQL insight value"
# Any-row alerts fail loud past this many rows: silently truncating could skip the breaching row
# (a false negative), which is worse than asking the user to add a LIMIT or aggregate the query.
# Deliberately conservative to start — easy to raise if users ask for more. Mirrored in the
# frontend preview as ``HOGQL_ANY_ROW_MAX_ROWS`` (frontend/src/lib/components/Alerts/alertFormLogic.ts);
# keep the two in sync.
ANY_ROW_MAX_ROWS = 50
# last_row reads the tail, so a result truncated at HogQL's hard cap can't be trusted (the real
# last row may have been dropped). Fail loud rather than alert on a truncated tail. first_row reads
# the head, which truncation never touches, so it has no such limit — use it (with a DESC ORDER BY)
# for queries that would otherwise return too many rows.
LAST_ROW_MAX_ROWS = MAX_SELECT_RETURNED_ROWS


class HogQLExtractor:
    """Normalize a HogQL/SQL-backed insight into ``ComparableSeries``.

    The config picks which result column to evaluate (defaulting to the single numeric column)
    and how to read the rows:
      - ``last_row``: the query is ordered oldest->newest; the last row is the current value.
      - ``first_row``: the query is ordered newest->oldest; the first row is the current value.
        The head is unaffected by result truncation and pairs with a user ``LIMIT``, so this is
        the mode for queries that would otherwise return very many rows.
      - ``any_row``: every row is checked and fires if any value breaches, labeling each row.
    The shared comparator interprets the resulting series either way.

    PREVIEW MIRROR CONTRACT: the configure-time preview re-implements this extractor's decision
    rules in TypeScript (``deriveHogQLAlertPreview`` in
    frontend/src/lib/components/Alerts/alertFormLogic.ts) so the modal can preview instantly from
    the already-loaded result. The mirror is advisory only — this extractor is the sole authority
    at evaluation time — but if you change any of these rules, update the mirror to match:
      1. value-column resolution: explicit ``column`` -> single column -> single numeric column
      2. numeric classification: most recent non-None cell decides; bools are not numeric
      3. ``None`` cells evaluate as 0
      4. label-column resolution: explicit -> first non-evaluated column -> row number
      5. empty result evaluates as 0 (zero sentinel)
      6. any-row cap: ``ANY_ROW_MAX_ROWS`` (mirrored as ``HOGQL_ANY_ROW_MAX_ROWS``)
      7. anchor row: ``last_row`` reads the tail, ``first_row`` the head; both yield (previous, current)
    """

    def extract(self, alert: AlertConfiguration, insight: Insight, query: Any) -> ExtractionResult:
        # ``query`` is unused (Protocol signature): the extractor recomputes via the insight.
        condition = AlertCondition.model_validate(alert.condition)
        config = HogQLAlertConfig.model_validate(alert.config or {"type": "HogQLAlertConfig", "evaluation": "last_row"})
        evaluation = config.evaluation

        calculation_result = calculate_for_query_based_insight(
            insight,
            team=alert.team,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=None,
            analytics_props={"source": EventSource.ALERT},
        )
        rows = calculation_result.result
        # ``None`` (vs an empty list) means the query layer swallowed an error — raise to avoid a
        # misfire, matching the trends extractor's handling of a None result.
        if rows is None:
            raise RuntimeError(f"No results found for insight with alert id = {alert.id}")
        if not isinstance(rows, list):
            raise AlertExtractionError(f"SQL alert query returned an unexpected result shape ({type(rows).__name__}).")
        if len(rows) == 0:
            # No rows means the metric is genuinely 0 this check (matching trends), so a lower
            # bound can still breach.
            return ExtractionResult(
                series=[zero_sentinel_series()],
                is_breakdown=False,
                subject=_HOGQL_SUBJECT,
                framed=False,
                empty_query_result=True,
            )

        # Row caps are checked before column resolution so an oversized result gets the clearer
        # "too many rows" error rather than a column-resolution one. last_row reads the tail, which
        # a truncated result destroys, so fail loud at the hard cap; first_row reads the head and is
        # unaffected, so it has no cap.
        if evaluation == HogQLAlertEvaluation.ANY_ROW and len(rows) > ANY_ROW_MAX_ROWS:
            raise AlertExtractionError(
                f"Any-row SQL alerts evaluate at most {ANY_ROW_MAX_ROWS} rows, but the query returned "
                f"{len(rows)} — add a LIMIT or aggregate the query."
            )
        if evaluation == HogQLAlertEvaluation.LAST_ROW and len(rows) >= LAST_ROW_MAX_ROWS:
            raise AlertExtractionError(
                f"Last-row SQL alerts can't trust a result of {len(rows)}+ rows — it may be truncated, so "
                "the last row might not be the real one. Add ORDER BY ... LIMIT, aggregate, or use first-row "
                "evaluation with a newest-first ordering."
            )

        columns = calculation_result.columns if isinstance(calculation_result.columns, list) else None
        column_names = [str(c) for c in columns] if columns else None
        value_index = _resolve_value_column_index(config.column, column_names, rows)

        if evaluation == HogQLAlertEvaluation.ANY_ROW:
            # Rows are entities (e.g. one per country), not a time axis — relative change between
            # unrelated rows is meaningless. validate_alert_config enforces this at configuration
            # time; this is the evaluation-time backstop.
            if condition.type != AlertConditionType.ABSOLUTE_VALUE:
                raise AlertExtractionError("Any-row SQL alerts only support absolute value conditions.")
            label_index = _resolve_label_column_index(config.label_column, column_names, value_index, rows)
            series = []
            for i, row in enumerate(rows):
                value = _numeric_cell(row, value_index, position=f"row {i + 1}")
                series.append(
                    ComparableSeries(
                        label=_label_for_row(row, i, label_index),
                        points=[SeriesPoint(date=None, value=value)],
                        current_index=0,
                    )
                )
            return ExtractionResult(
                series=series, is_breakdown=True, subject=_HOGQL_SUBJECT, framed=False, aggregate_breaches=True
            )

        # last_row / first_row: read the (previous, current) pair from the tail or head respectively.
        values = _anchor_values(rows, value_index, from_head=evaluation == HogQLAlertEvaluation.FIRST_ROW)
        is_relative = condition.type in (AlertConditionType.RELATIVE_INCREASE, AlertConditionType.RELATIVE_DECREASE)
        if is_relative and len(values) < 2:
            raise AlertExtractionError("Relative alerts on SQL insights need at least two rows (current and previous).")

        points = [SeriesPoint(date=None, value=v) for v in values]
        series_label = column_names[value_index] if column_names and value_index < len(column_names) else "result"
        single = ComparableSeries(label=series_label, points=points, current_index=len(points) - 1)
        return ExtractionResult(series=[single], is_breakdown=False, subject=_HOGQL_SUBJECT, framed=False)


def _resolve_value_column_index(configured: str | None, column_names: list[str] | None, rows: list) -> int:
    """Pick the result column the alert evaluates.

    An explicit column name wins; otherwise a single-column result is used as-is, and a wider
    result falls back to the single numeric column — ambiguity (0 or 2+ numeric columns) is a
    configuration error rather than a guess.
    """
    if configured is not None:
        if not column_names:
            raise AlertExtractionError(
                f"SQL alert is configured to evaluate column '{configured}' but the result has no column metadata."
            )
        if configured not in column_names:
            raise AlertExtractionError(
                f"SQL alert column '{configured}' is not in the result columns ({', '.join(column_names)})."
            )
        return column_names.index(configured)

    width = _row_width(rows)
    if width == 1:
        return 0

    numeric_indexes = [i for i in range(width) if _column_is_numeric(rows, i)]
    if len(numeric_indexes) == 1:
        return numeric_indexes[0]
    described = f" ({', '.join(column_names)})" if column_names else ""
    raise AlertExtractionError(
        f"SQL alert query returns {width} columns{described} and "
        f"{'none' if not numeric_indexes else 'more than one'} of them is numeric — "
        "pick the column to evaluate in the alert settings."
    )


def _resolve_label_column_index(
    configured: str | None, column_names: list[str] | None, value_index: int, rows: list
) -> int | None:
    if configured is not None:
        if not column_names or configured not in column_names:
            described = f" ({', '.join(column_names)})" if column_names else ""
            raise AlertExtractionError(
                f"SQL alert label column '{configured}' is not in the result columns{described}."
            )
        return column_names.index(configured)
    # Default: the first column that isn't being evaluated (e.g. the GROUP BY key).
    width = _row_width(rows)
    for i in range(width):
        if i != value_index:
            return i
    return None


def _label_for_row(row: Any, index: int, label_index: int | None) -> str:
    if label_index is not None and isinstance(row, list | tuple) and label_index < len(row):
        cell = row[label_index]
        if cell is not None:
            return str(cell)
    return f"row {index + 1}"


def _row_width(rows: list) -> int:
    last = rows[-1]
    if not isinstance(last, list | tuple):
        raise AlertExtractionError(
            f"SQL alert query must return rows as lists/tuples (got {type(last).__name__} for the last row)."
        )
    return len(last)


def _column_is_numeric(rows: list, index: int) -> bool:
    """Classify a column by its most recent non-None value (all-None columns don't count)."""
    for row in reversed(rows):
        if not isinstance(row, list | tuple) or index >= len(row):
            return False
        cell = row[index]
        if cell is None:
            continue
        return not isinstance(cell, bool) and isinstance(cell, int | float | Decimal)
    return False


def _anchor_values(rows: list, value_index: int, *, from_head: bool) -> list[float]:
    """Extract the (previous, current) values for last_row/first_row, current last.

    Only the head or tail is inspected — these modes never read past the second row in from
    the anchor end, so validating the rest would waste work on data we won't use. ``last_row``
    takes the tail ``[..previous, current]``; ``first_row`` takes the head ``[current, previous..]``
    (newest first) and reverses it to the same ``[..previous, current]`` shape, so the caller can
    treat the last element as the anchor either way.
    """
    if from_head:
        head = rows[:2]
        positions = ["first row", "second row"][: len(head)]
        cells = [_numeric_cell(row, value_index, position=position) for position, row in zip(positions, head)]
        return list(reversed(cells))
    tail = rows[-2:]
    positions = ["second-to-last row", "last row"] if len(tail) == 2 else ["last row"]
    return [_numeric_cell(row, value_index, position=position) for position, row in zip(positions, tail)]


def _numeric_cell(row: Any, index: int, *, position: str) -> float:
    """Coerce one result cell to a float. ``None`` buckets become 0 to match trends handling."""
    if not isinstance(row, list | tuple):
        raise AlertExtractionError(
            f"SQL alert query must return rows as lists/tuples (got {type(row).__name__} for the {position})."
        )
    if index >= len(row):
        raise AlertExtractionError(f"SQL alert query returned a {position} with too few columns.")
    raw = row[index]
    if raw is None:
        return 0.0
    # ClickHouse Decimal columns surface as decimal.Decimal; accept them alongside int/float.
    if isinstance(raw, bool) or not isinstance(raw, int | float | Decimal):
        raise AlertExtractionError(
            f"SQL alert query must return a numeric value to evaluate (got {type(raw).__name__} for the {position})."
        )
    value = float(raw)
    if not math.isfinite(value):
        raise AlertExtractionError(
            f"SQL alert query must return a finite numeric value (got {raw} for the {position})."
        )
    return value
