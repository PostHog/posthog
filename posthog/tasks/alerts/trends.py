from typing import NotRequired, Optional, TypedDict, cast

import numpy as np

from posthog.schema import ChartDisplayType, FunnelsQuery, IntervalType, TrendsQuery

from posthog.caching.insight_result import InsightResult
from posthog.hogql_queries.utils.breakdowns import has_breakdown_filter
from posthog.hogql_queries.utils.result_series import has_formula_results
from posthog.tasks.alerts.metric_definition import _formulas
from posthog.tasks.alerts.utils import NON_TIME_SERIES_DISPLAY_TYPES


# TODO: move the TrendResult UI type to schema.ts and use that instead
class TrendResult(TypedDict):
    action: dict
    actions: list[dict]
    count: int
    data: list[float]
    days: list[str]
    dates: list[str]
    label: str
    labels: list[str]
    breakdown_value: str | int | list[str]
    aggregated_value: NotRequired[float]
    status: str | None
    compare_label: str | None
    compare: bool
    persons_urls: list[dict]
    persons: dict
    filter: dict


def _is_non_time_series_trend(query: TrendsQuery) -> bool:
    return bool(query.trendsFilter and query.trendsFilter.display in NON_TIME_SERIES_DISPLAY_TYPES)


def query_excludes_incomplete_periods(query: TrendsQuery | FunnelsQuery) -> bool:
    """When the insight already clips the ongoing interval via
    DateRange.excludeIncompletePeriods, every returned point is complete and
    the alert machinery must not drop or skip the trailing one."""
    return bool(query.dateRange and query.dateRange.excludeIncompletePeriods)


def _drop_incomplete_current_interval(
    data: np.ndarray, dates: list[str], is_non_time_series: bool, *, drop_current: bool
) -> tuple[np.ndarray, list[str]]:
    """Drop the current (incomplete) interval — always the last element.

    The query does not set date_to, so the result includes the ongoing
    interval whose value is still accumulating.  Comparing this partial
    value against complete historical intervals causes systematic false
    positives. Pass drop_current=False when the query already excludes
    incomplete periods, so a complete trailing interval isn't lost too;
    it has no default so callers can't silently drop a complete point.
    """
    if drop_current and not is_non_time_series and len(data) > 1:
        data = data[:-1]
        dates = dates[:-1] if dates else dates
    return data, dates


def _has_breakdown(query: TrendsQuery) -> bool:
    return has_breakdown_filter(query.breakdownFilter)


def _date_range_override_for_intervals(query: TrendsQuery, last_x_intervals: int = 1) -> Optional[dict]:
    """
    Resulting filter overrides don't set 'date_to' so we always get value for current interval.
    last_x_intervals controls how many intervals to look back to
    """
    assert last_x_intervals > 0

    match query.interval:
        case IntervalType.DAY:
            date_from = f"-{last_x_intervals}d"
        case IntervalType.WEEK:
            date_from = f"-{last_x_intervals}w"
        case IntervalType.MONTH:
            date_from = f"-{last_x_intervals}m"
        case IntervalType.QUARTER:
            date_from = f"-{last_x_intervals}q"
        case IntervalType.YEAR:
            date_from = f"-{last_x_intervals}y"
        case _:
            date_from = f"-{last_x_intervals}h"

    return {"date_from": date_from}


def _defined_result_count(query: TrendsQuery) -> int:
    """How many results the query defines outside a breakdown: one per formula when formulas apply, else one per series."""
    if query.trendsFilter and query.trendsFilter.display == ChartDisplayType.CALENDAR_HEATMAP:
        # The heatmap runner reports one row for series 0, whatever the series and formulas are.
        return 1
    source = query.model_dump(mode="json")
    return len(_formulas(source)) if has_formula_results(source) else len(query.series)


def _pick_series_result(series_index: int, results: InsightResult, query: TrendsQuery) -> TrendResult:
    # A top-level import is circular: the evaluation package imports this module while it loads.
    from products.alerts.backend.evaluation.contract import (  # noqa: PLC0415
        AlertDataUnavailableError,
        AlertExtractionError,
    )

    if not 0 <= series_index < _defined_result_count(query):
        raise AlertExtractionError(
            "This alert watches a series or formula the insight no longer has. Edit the alert and choose what to watch."
        )
    rows = cast(list[TrendResult], results.result)
    position = series_index
    if any(isinstance(row.get("order"), int) for row in rows):
        # In compare mode the runner lists each formula's previous-period row right after its current row, but
        # lists every series' current row before any previous row. Only `order` and `compare_label` find the row.
        rows = [row for row in rows if row.get("order") == series_index and row.get("compare_label") != "previous"]
        position = 0
    if position >= len(rows):
        raise AlertDataUnavailableError(
            "The insight returned fewer results than it defines, so this check couldn't evaluate. The next check will try again."
        )
    return rows[position]
