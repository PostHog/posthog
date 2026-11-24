"""Adapters from a tile's cached query result to chart-ready frames (`Frame` in facade/contracts.py).

Each query kind has one adapter that turns its cached response into frames, and a chart reads only frames.
An adapter knows nothing about charts and a chart knows nothing about queries.
The shape follows Dash's `DataFrame` (packages/schema/src/frame.ts in PostHog/dash).
"""

import json
import datetime as dt
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from posthog.schema import ChartDisplayType, MetricsQuery, TrendsQuery

from posthog.caching.insight_result import InsightResult
from posthog.hogql_queries.apply_dashboard_filters import WRAPPER_NODE_KINDS
from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL
from posthog.hogql_queries.utils.result_series import get_series_key

from products.dashboards.backend.facade.contracts import Frame, FrameField, FrameMeta

# Trends displays that draw one value per interval. The others show one number per series.
_TIME_SERIES_DISPLAYS = {
    None,
    ChartDisplayType.ACTIONS_LINE_GRAPH,
    ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE,
    ChartDisplayType.ACTIONS_AREA_GRAPH,
    ChartDisplayType.ACTIONS_BAR,
    ChartDisplayType.ACTIONS_STACKED_BAR,
    ChartDisplayType.ACTIONS_UNSTACKED_BAR,
}
_BREAKDOWN_LABELS = {BREAKDOWN_NULL_STRING_LABEL: "None", BREAKDOWN_OTHER_STRING_LABEL: "Other"}


def insight_frames(query: Mapping[str, Any], result: InsightResult) -> list[Frame] | None:
    """Frames for a cached insight result, or None when its query kind or display has no frames yet.

    `query` is the query the result was computed with, dashboard and tile filters applied.
    """
    source = _source(query)
    if source is None or not isinstance(result.result, list):
        return None
    try:
        if source.get("kind") == "TrendsQuery":
            return _trends_frames(TrendsQuery.model_validate(source), result)
        if source.get("kind") == "MetricsQuery":
            return _metrics_frames(MetricsQuery.model_validate(source), result)
    except ValidationError:
        return None
    return None


def has_frames(query: Mapping[str, Any]) -> bool:
    """Whether `insight_frames` can return frames for this query's kind and display, read without validating it."""
    source = _source(query)
    if source is None:
        return False
    if source.get("kind") == "MetricsQuery":
        return True
    trends_filter = source.get("trendsFilter")
    display = trends_filter.get("display") if isinstance(trends_filter, Mapping) else None
    return source.get("kind") == "TrendsQuery" and display in _TIME_SERIES_DISPLAYS


def _source(query: Mapping[str, Any]) -> Mapping[str, Any] | None:
    source = query.get("source") if query.get("kind") in WRAPPER_NODE_KINDS else query
    return source if isinstance(source, Mapping) else None


def _trends_frames(query: TrendsQuery, result: InsightResult) -> list[Frame] | None:
    if (query.trendsFilter.display if query.trendsFilter else None) not in _TIME_SERIES_DISPLAYS:
        return None
    timezone = ZoneInfo(result.timezone or "UTC")
    interval = query.interval.value if query.interval else "day"
    current = _meta(result.resolved_date_range, interval, previous=False)
    previous = _meta(result.resolved_compare_date_range, interval, previous=True)
    trends_filter = query.trendsFilter
    has_formula = bool(
        trends_filter and (trends_filter.formula or trends_filter.formulas or trends_filter.formulaNodes)
    )
    action_names = {int(key): name for key, name in (result.action_names or {}).items() if key.isdigit()}
    frames: list[Frame] = []
    for index, series in enumerate(result.result or []):
        is_previous = series.get("compare_label") == "previous"
        name = _trends_series_name(series, query, action_names, has_formula)
        frames.append(
            Frame(
                name=f"{name} (previous)" if is_previous else name,
                labels=_trends_series_labels(series, index),
                fields=[
                    FrameField(
                        name="time", type="time", values=[_wall_clock_ms(day, timezone) for day in series["days"]]
                    ),
                    FrameField(name="value", type="number", values=list(series["data"])),
                ],
                meta=previous if is_previous else current,
            )
        )
    return frames


def _trends_series_name(
    series: Mapping[str, Any], query: TrendsQuery, action_names: Mapping[int, str], has_formula: bool
) -> str:
    # With a breakdown, PostHog's label is the breakdown value, prefixed by the event when there are several series.
    label = _readable_breakdown(series["label"])
    custom_name = series.get("custom_name")
    breakdown_value = series.get("breakdown_value")
    if breakdown_value is None:
        return custom_name or label
    if has_formula:
        # A formula row's label is the formula's name, the same for every breakdown value.
        return f"{label} - {_breakdown_label(breakdown_value)}"
    if len(query.series) == 1 or not custom_name:
        return label
    return f"{custom_name} - {_label_breakdown(series, label, query, action_names)}"


def _label_breakdown(series: Mapping[str, Any], label: str, query: TrendsQuery, action_names: Mapping[int, str]) -> str:
    # The label is "<series key> - <breakdown>", and only the label holds a cohort's name, not its ID.
    order = series.get("order")
    if isinstance(order, int) and 0 <= order < len(query.series):
        key = get_series_key(query.series[order].model_dump(), action_names) or "All events"
        if label.startswith(f"{key} - "):
            return label[len(key) + 3 :]
    return _breakdown_label(series["breakdown_value"])


def _trends_series_labels(series: Mapping[str, Any], index: int) -> dict[str, str]:
    # Enough to find the series again: its position in the query and its breakdown value.
    labels = {"series_index": str(series.get("order", index))}
    breakdown_value = series.get("breakdown_value")
    if breakdown_value is not None:
        labels["breakdown_value"] = breakdown_value if isinstance(breakdown_value, str) else json.dumps(breakdown_value)
    return labels


def _breakdown_label(value: Any) -> str:
    values = value if isinstance(value, list) else [value]
    return ", ".join(_BREAKDOWN_LABELS.get(str(each), str(each)) for each in values)


def _readable_breakdown(label: str) -> str:
    for token, readable in _BREAKDOWN_LABELS.items():
        label = label.replace(token, readable)
    return label


def _metrics_frames(query: MetricsQuery, result: InsightResult) -> list[Frame]:
    # Imported here: a module-level import puts the metrics product on core's request path.
    from products.metrics.backend.facade.api import metrics_query_interval

    date_range = result.resolved_date_range
    meta = _meta(date_range, None, previous=False)
    if meta.date_from is not None and meta.date_to is not None:
        # The runner resolves its range in the project's timezone, and the cached strings keep only an offset.
        # Elapsed time differs across a DST change, so the interval is resolved in the same zone.
        timezone = ZoneInfo(result.timezone or "UTC")
        try:
            interval = metrics_query_interval(
                query=query, date_from=meta.date_from.astimezone(timezone), date_to=meta.date_to.astimezone(timezone)
            )
        except ValueError:
            interval = None
        meta = FrameMeta(interval=interval, date_from=meta.date_from, date_to=meta.date_to)
    series_list: list[Mapping[str, Any]] = result.result or []
    # Same naming as the metrics chart (metricsSeries.ts formatSeriesNames).
    several_clauses = len({series.get("clause") for series in series_list if series.get("clause")}) > 1
    frames: list[Frame] = []
    for series in series_list:
        labels: dict[str, str] = series.get("labels") or {}
        prefix = f"{series['clause']} · " if several_clauses and series.get("clause") else ""
        name = ", ".join(f"{key}={value}" for key, value in labels.items()) if labels else None
        frames.append(
            Frame(
                name=prefix + (name or series.get("metricName") or series.get("clause") or "value"),
                labels=labels,
                fields=[
                    FrameField(
                        name="time",
                        type="time",
                        values=[_epoch_ms(_datetime(point["time"])) for point in series["points"]],
                    ),
                    FrameField(
                        name="value",
                        type="number",
                        values=[point["value"] for point in series["points"]],
                        unit=series.get("unit"),
                    ),
                ],
                meta=meta,
            )
        )
    return frames


def _meta(date_range: Mapping[str, Any] | None, interval: str | None, *, previous: bool) -> FrameMeta:
    return FrameMeta(
        interval=interval,
        date_from=_datetime(date_range["date_from"]) if date_range else None,
        date_to=_datetime(date_range["date_to"]) if date_range else None,
        previous=previous,
    )


def _datetime(value: dt.datetime | str) -> dt.datetime:
    return value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)


def _wall_clock_ms(day: str, timezone: ZoneInfo) -> int:
    # Trends buckets are wall-clock times in the project's timezone, without an offset.
    return _epoch_ms(dt.datetime.fromisoformat(day).replace(tzinfo=timezone))


def _epoch_ms(value: dt.datetime) -> int:
    return int(value.timestamp() * 1000)
