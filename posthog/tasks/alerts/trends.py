from typing import NotRequired, Optional, TypedDict, cast

import numpy as np

from posthog.schema import IntervalType, TrendsAlertConfig, TrendsQuery

from posthog.caching.fetch_from_cache import InsightResult
from posthog.hogql_queries.insights.utils.breakdowns import has_breakdown_filter
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


def _drop_incomplete_current_interval(
    data: np.ndarray, dates: list[str], is_non_time_series: bool
) -> tuple[np.ndarray, list[str]]:
    """Drop the current (incomplete) interval — always the last element.

    The query does not set date_to, so the result includes the ongoing
    interval whose value is still accumulating.  Comparing this partial
    value against complete historical intervals causes systematic false
    positives.
    """
    if not is_non_time_series and len(data) > 1:
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


def _pick_series_result(config: TrendsAlertConfig, results: InsightResult) -> TrendResult:
    series_index = config.series_index
    result = cast(list[TrendResult], results.result)[series_index]

    return result
