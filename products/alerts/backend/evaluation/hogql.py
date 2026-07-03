import math
from decimal import Decimal
from typing import Any

from posthog.schema import AlertCondition, AlertConditionType, HogQLAlertConfig, HogQLAlertEvaluation

from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import EventSource
from posthog.tasks.alerts.detector import _compute_min_samples_for_detector

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    SimulationContext,
    execution_mode_for_alert,
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
_DEFAULT_HOGQL_CONFIG = {"type": "HogQLAlertConfig", "evaluation": "last_row"}


def hogql_config_or_default(raw: dict | None) -> HogQLAlertConfig:
    """Validate a stored SQL alert config, defaulting an absent one to last-row evaluation."""
    return HogQLAlertConfig.model_validate(raw or _DEFAULT_HOGQL_CONFIG)


def _calculate_rows_and_columns(
    insight: Insight, team: Any, *, user: Any, execution_mode: ExecutionMode
) -> tuple[list, list[str] | None]:
    """Run a SQL insight and return (rows, column_names) — the fetch-and-validate prologue shared by
    the threshold and detector extractors. A ``None`` result means the query layer swallowed an error
    (raise to avoid a misfire, matching trends); a non-list result is a malformed shape.
    """
    calculation_result = calculate_for_query_based_insight(
        insight,
        team=team,
        execution_mode=execution_mode,
        user=user,
        analytics_props={"source": EventSource.ALERT},
    )
    rows = calculation_result.result
    if rows is None:
        raise RuntimeError(f"No results found for insight with id = {insight.id}")
    if not isinstance(rows, list):
        raise AlertExtractionError(f"SQL alert query returned an unexpected result shape ({type(rows).__name__}).")
    columns = calculation_result.columns if isinstance(calculation_result.columns, list) else None
    column_names = [str(c) for c in columns] if columns else None
    return rows, column_names


def _check_row_caps(rows: list, evaluation: HogQLAlertEvaluation) -> None:
    """Fail loud on a result the evaluation mode can't trust. last_row reads the tail, which HogQL's
    hard cap can silently truncate (so the last row might not be the real one); any_row would skip a
    breaching row past its cap. first_row reads the head (truncation-immune), so it has no cap. Shared
    by the threshold and detector extractors so the guard can't drift between them.
    """
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


def _value_column_label(column_names: list[str] | None, value_index: int) -> str:
    """Name the evaluated value column, falling back to 'result' when there's no column metadata."""
    return column_names[value_index] if column_names and value_index < len(column_names) else "result"


class HogQLExtractor:
    """Normalize a HogQL/SQL-backed insight into ``ComparableSeries``.

    The config picks which result column to evaluate (defaulting to the single numeric column)
    and how to read the rows:
      - ``last_row``: the query is ordered oldest->newest; the last row is the current value.
      - ``first_row``: the query is ordered newest->oldest; the first row is the current value.
        The head is unaffected by result truncation and pairs with a user ``LIMIT``, so this is
        the mode for queries that would otherwise return very many rows.
      - ``any_row``: every row is checked and fires if any value breaches, labeling each row.
    In every mode the label column (the METRIC column in the preview) names the evaluated row(s).
    The shared comparator interprets the resulting series either way.

    PREVIEW MIRROR CONTRACT: the configure-time preview re-implements this extractor's decision
    rules in TypeScript (``deriveHogQLAlertPreview`` in
    frontend/src/lib/components/Alerts/alertFormLogic.ts) so the modal can preview instantly from
    the already-loaded result. The mirror is advisory only — this extractor is the sole authority
    at evaluation time — but if you change any of these rules, update the mirror to match:
      1. value-column resolution: explicit ``column`` -> single column -> single numeric column
      2. numeric classification: most recent non-None cell decides; bools are not numeric
      3. ``None`` cells evaluate as 0
      4. label-column resolution: explicit -> first non-evaluated column (the mirror reproduces
         this). The fallback when a row has no label cell differs by surface and is NOT mirrored:
         the preview falls back to the row number (it shows every row, so numbering keeps them
         distinct), whereas this extractor's single evaluated row (last_row/first_row) falls back
         to the value column name — there's only one row, so a number carries no information.
      5. empty result evaluates as 0 (zero sentinel)
      6. any-row cap: ``ANY_ROW_MAX_ROWS`` (mirrored as ``HOGQL_ANY_ROW_MAX_ROWS``)
      7. anchor row: ``last_row`` reads the tail, ``first_row`` the head; both yield (previous, current)
    """

    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        # ``query`` is unused (Protocol signature): the extractor recomputes via the insight.
        condition = AlertCondition.model_validate(alert.condition)
        config = hogql_config_or_default(alert.config)
        evaluation = config.evaluation

        rows, column_names = _calculate_rows_and_columns(
            insight, alert.team, user=alert.created_by, execution_mode=execution_mode
        )
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

        # Checked before column resolution so an oversized result gets the clearer "too many rows"
        # error rather than a column-resolution one.
        _check_row_caps(rows, evaluation)

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
        # Label the evaluated row by its label column (the METRIC column shown in the preview),
        # falling back to the value column name when the result has no distinct label column.
        label_index = _resolve_label_column_index(config.label_column, column_names, value_index, rows)
        anchor_row = rows[0] if evaluation == HogQLAlertEvaluation.FIRST_ROW else rows[-1]
        label_cell = _label_cell(anchor_row, label_index)
        series_label = label_cell if label_cell is not None else _value_column_label(column_names, value_index)
        single = ComparableSeries(label=series_label, points=points, current_index=len(points) - 1)
        # Surface the label in the breach message only when it's a real label cell — the value-column
        # fallback would just read "The SQL insight value (value) (...)", which adds nothing.
        return ExtractionResult(
            series=[single],
            is_breakdown=False,
            subject=_HOGQL_SUBJECT,
            framed=False,
            include_series_label=label_cell is not None,
        )


def extract_hogql_detector_series(
    insight: Insight,
    team: Any,
    config: HogQLAlertConfig,
    detector_config: dict[str, Any],
    *,
    execution_mode: ExecutionMode,
    user: Any = None,
) -> ExtractionResult:
    """Build the full ordered value series an anomaly detector scores from a SQL/HogQL insight.

    Shared by the alert-check extractor and the read-only simulation. Unlike trends, a SQL query is
    self-contained — its rows *are* the history, so there's no wider lookback window to refetch; the
    query must return enough rows for the detector's window. Only ``last_row``/``first_row`` apply:
    ``any_row`` rows are unrelated entities, not a time axis, so scoring change across them is
    meaningless. Too few rows to fill the window yields an empty series (uncomputed); an empty result
    yields an empty series flagged ``empty_query_result`` (the metric is genuinely 0).
    """
    if config.evaluation == HogQLAlertEvaluation.ANY_ROW:
        raise AlertExtractionError(
            "Anomaly detection isn't supported for any-row SQL alerts — its rows are unrelated "
            "entities, not a time series. Use last-row or first-row evaluation."
        )

    rows, column_names = _calculate_rows_and_columns(insight, team, user=user, execution_mode=execution_mode)
    if len(rows) == 0:
        return ExtractionResult(
            series=[], is_breakdown=False, subject=_HOGQL_SUBJECT, framed=False, empty_query_result=True
        )
    # last_row scores the tail as the current value, so the same truncation guard the threshold path
    # enforces applies here — a tail truncated at HogQL's hard cap would score the wrong "current" row.
    _check_row_caps(rows, config.evaluation)

    value_index = _resolve_value_column_index(config.column, column_names, rows)
    # The series is the value column across every row, oldest->newest so the detector scores the
    # latest point against its history. first_row results are newest-first, so reverse them.
    from_head = config.evaluation == HogQLAlertEvaluation.FIRST_ROW
    ordered = list(reversed(rows)) if from_head else rows
    # position reports the original result-row number (not the reversed index) for clear error text.
    n = len(rows)
    values = [
        _numeric_cell(row, value_index, position=f"row {n - i if from_head else i + 1}")
        for i, row in enumerate(ordered)
    ]

    # Too few points to score → report uncomputed (None). SQL rows are the series verbatim — unlike
    # trends, there's no incomplete-interval drop to offset — so the detector's own minimum is the
    # exact cutoff. (Trends adds +1 to compensate for the dropped interval; SQL must not, or a query
    # returning exactly the detector's minimum would be wrongly rejected as "not enough data".)
    min_samples = _compute_min_samples_for_detector(detector_config)
    if len(values) < min_samples:
        return ExtractionResult(series=[], is_breakdown=False, subject=_HOGQL_SUBJECT, framed=False)

    # Score only the most recent window the detector needs (current stays last). A SQL query can
    # return a large result, and detectors like KNN/LOF/OCSVM train on every point handed in — so
    # without this bound a big result set would make alert workers train on tens of thousands of
    # points each check. The trends path bounds the same way via its date-range fetch.
    values = values[-min_samples:]

    # Label the evaluated (current) row by its label column — same as the threshold path — so an
    # anomaly breach names e.g. "Burn rate 24h" rather than the bare value-column name. The current
    # row is the original latest row (head for first_row, tail otherwise), regardless of the slice.
    label_index = _resolve_label_column_index(config.label_column, column_names, value_index, rows)
    anchor_row = rows[0] if from_head else rows[-1]
    label_cell = _label_cell(anchor_row, label_index)
    series_label = label_cell if label_cell is not None else _value_column_label(column_names, value_index)

    points = [SeriesPoint(date=None, value=v) for v in values]
    single = ComparableSeries(label=series_label, points=points, current_index=len(points) - 1)
    return ExtractionResult(series=[single], is_breakdown=False, subject=_HOGQL_SUBJECT, framed=False)


class HogQLDetectorExtractor:
    """Detector-path extractor for SQL/HogQL insights — thin alert adapter over
    ``extract_hogql_detector_series`` (which the read-only simulation also uses), mirroring how
    ``TrendsDetectorExtractor`` wraps ``extract_detector_series``.
    """

    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        detector_config = alert.detector_config
        if not detector_config:
            raise ValueError("HogQLDetectorExtractor requires detector_config — dispatcher invariant violated")
        config = hogql_config_or_default(alert.config)
        return extract_hogql_detector_series(
            insight, alert.team, config, detector_config, execution_mode=execution_mode, user=alert.created_by
        )

    def simulate(self, insight: Insight, query: object, ctx: SimulationContext) -> tuple[ExtractionResult, str | None]:
        # SQL rows are their own series, so there's no chart interval — return None alongside. SQL has
        # no time axis to force fresh on, so the read-only simulation uses the cache-friendly mode.
        result = extract_hogql_detector_series(
            insight,
            ctx.team,
            hogql_config_or_default(ctx.config),
            ctx.extractor_config,
            execution_mode=execution_mode_for_alert(None, high_frequency=False),
            user=ctx.user,
        )
        return result, None


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


def _label_cell(row: Any, label_index: int | None) -> str | None:
    # None when there's no usable label cell — the caller picks the mode-specific fallback.
    if label_index is not None and isinstance(row, list | tuple) and label_index < len(row):
        cell = row[label_index]
        if cell is not None:
            return str(cell)
    return None


def _label_for_row(row: Any, index: int, label_index: int | None) -> str:
    cell = _label_cell(row, label_index)
    return cell if cell is not None else f"row {index + 1}"


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
