"""Query batch results as chart-ready frames, so a chart draws any target without knowing its language.

A frame is Dash's `DataFrame` (packages/schema/src/frame.ts in PostHog/dash): a name, labels, a time field in epoch
milliseconds, one or more value fields and meta. Each language's result has one converter here, and a node kind without
one of its own becomes a table. A result with no frame shape at all gets None, and its line says so with an error.

The frame types are the cached tiles' (`facade.contracts`), which also have the string, boolean and other fields a table
needs. The trends and metrics converters are ported from the cached tiles converters in `logic/frames.py`.
"""

import re
import json
import hashlib
import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any, Optional
from zoneinfo import ZoneInfo

import orjson
from pydantic import ValidationError
from rest_framework.utils.encoders import JSONEncoder

from posthog.schema import ChartDisplayType, TrendsQuery

from posthog.dataclasses import frozen
from posthog.hogql_queries.apply_dashboard_filters import WRAPPER_NODE_KINDS
from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL
from posthog.hogql_queries.utils.result_series import get_series_key

from products.dashboards.backend.facade.contracts import Frame, FrameField, FrameFieldType, FrameMeta
from products.dashboards.backend.facade.enums import QueryBatchLanguage, QueryBatchTargetFormat

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
# Trends displays that show one number per series. Metric, heatmaps, box plots and slope graphs carry other shapes and
# keep their raw result.
_AGGREGATED_DISPLAYS = {
    ChartDisplayType.BOLD_NUMBER,
    ChartDisplayType.ACTIONS_PIE,
    ChartDisplayType.ACTIONS_DONUT,
    ChartDisplayType.ACTIONS_PROPORTION_BAR,
    ChartDisplayType.ACTIONS_BAR_VALUE,
    ChartDisplayType.ACTIONS_TABLE,
    ChartDisplayType.WORLD_MAP,
}
_BREAKDOWN_LABELS = {BREAKDOWN_NULL_STRING_LABEL: "None", BREAKDOWN_OTHER_STRING_LABEL: "Other"}
# The label is trimmed after the match: `\s*` around a lazy group backtracks cubically on a run of spaces.
_LEGEND_LABEL = re.compile(r"\{\{([^{}]+)\}\}")
_TIME_TYPE = re.compile(r"date|time", re.IGNORECASE)
_NUMBER_TYPE = re.compile(r"int|float|decimal|double", re.IGNORECASE)
_DATE_ONLY_TYPE = re.compile(r"^(Nullable\()?Date(32)?\)?$")
_COMPOUND_TYPE = re.compile(r"^(Nullable\()?(Array|Map|Tuple|Nested)\(")
# An enum's labels can spell "time" or "int", so it is a string before the scalar checks read its type.
_ENUM_TYPE = re.compile(r"^(Nullable\()?(LowCardinality\()?(Nullable\()?Enum(8|16)?\(")
_NO_LABEL = "(none)"
# A template can repeat a long label, so the expanded name is cut while it is built.
MAX_LEGEND_NAME = 1024
# Above this many series, or this many label bytes repeated across the series' fields, a long table stays a table.
# Pivoting copies every label onto every number field, so a few large labels can grow a small result many times over.
MAX_PIVOT_SERIES = 1000
MAX_PIVOT_FIELDS = 20_000
MAX_PIVOT_LABEL_BYTES = 8 * 1024 * 1024
# A log table repeats its stream's labels on every line. Above this many label bytes, it has no frames.
MAX_STREAM_LABEL_BYTES = 8 * 1024 * 1024
# Each Prometheus series becomes a frame of its own, many times the size of the series in the response. Above this
# many series, it has no frames.
MAX_PROMETHEUS_SERIES = 1000
# A list of records with many distinct keys expands to rows x keys cells, so sparse records are bounded before allocation.
MAX_RECORD_FIELDS = 1000
MAX_RECORD_CELLS = 2_000_000


def frames_for(
    language: QueryBatchLanguage,
    query: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    legend: Optional[str] = None,
    target_format: Optional[QueryBatchTargetFormat] = None,
    timezone: Optional[str] = None,
) -> Optional[list[dict[str, Any]]]:
    """The frames of one query batch result as JSON, or None when its kind has no frame shape.

    `query` is the query node that ran, or for LogQL nothing. `result` is the runner's response as a dict. `timezone` is
    the project's, for responses whose buckets are in project wall time but do not name the timezone.
    """
    frames = _frames(language, query, result, target_format, timezone)
    if frames is None:
        return None
    if legend:
        frames = [_with_legend(frame, legend, len(frames)) for frame in frames]
    return [frame_json(frame) for frame in frames]


def _frames(
    language: QueryBatchLanguage,
    query: Mapping[str, Any],
    result: Mapping[str, Any],
    target_format: Optional[QueryBatchTargetFormat],
    timezone: Optional[str] = None,
) -> Optional[list[Frame]]:
    as_table = target_format == QueryBatchTargetFormat.TABLE
    if language == QueryBatchLanguage.LOGQL:
        data = result.get("results")
        return prometheus_frames(data) if isinstance(data, Mapping) else None
    source = _source(query)
    if source is None:
        return None
    kind = source.get("kind")
    if kind == "HogQLQuery":
        return hogql_frames(result, pivot=not as_table)
    if kind == "TraceSpansAggregationQuery":
        return span_aggregation_frames(result, as_table=as_table)
    if kind == "TraceSpansQuery":
        return span_list_frames(result)
    if kind == "MetricsQuery":
        return metrics_frames(result)
    if kind == "TrendsQuery":
        try:
            return trends_frames(TrendsQuery.model_validate(source), result)
        except ValidationError:
            return None
    if kind == "StickinessQuery":
        return stickiness_frames(result)
    if kind == "LifecycleQuery":
        return lifecycle_frames(source, result, timezone)
    if kind == "FunnelsQuery":
        return funnels_frames(source, result, timezone)
    if kind == "RetentionQuery":
        return retention_frames(result)
    return table_frames(str(kind), result)


def shape_kind(language: QueryBatchLanguage, query: Mapping[str, Any]) -> str:
    """What a line without frames names as its unsupported shape: the node kind, or the language when there is none."""
    source = None if language == QueryBatchLanguage.LOGQL else _source(query)
    kind = source.get("kind") if source else None
    return str(kind) if kind else language.value


def _source(query: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    source = query.get("source") if query.get("kind") in WRAPPER_NODE_KINDS else query
    return source if isinstance(source, Mapping) else None


def legend_name(template: str, labels: Mapping[str, str]) -> str:
    """Grafana's legend format: `{{label}}` is that label's value, dotted names included, and a missing label is empty."""
    parts: list[str] = []
    size = position = 0
    for match in _LEGEND_LABEL.finditer(template):
        for part in (template[position : match.start()], labels.get(match.group(1).strip(), "")):
            parts.append(part[: MAX_LEGEND_NAME - size])
            size += len(parts[-1])
        position = match.end()
    parts.append(template[position:][: MAX_LEGEND_NAME - size])
    return "".join(parts)


def _with_legend(frame: Frame, template: str, count: int) -> Frame:
    labels = dict(frame.labels)
    for field in frame.fields:
        labels.update(field.labels or {})
    # A template without labels names a lone series, as Dash names the one frame of a single-number query.
    if not _LEGEND_LABEL.search(template) and count > 1:
        return frame
    return Frame(name=legend_name(template, labels), labels=frame.labels, fields=frame.fields, meta=frame.meta)


def frame_json(frame: Frame) -> dict[str, Any]:
    """A frame as the line carries it, with `meta.end` (its last time) and a content `hash`.

    A later request can send back `{end, hash}` to say what it holds, so the server can answer with only newer points.
    """
    fields = [
        {
            "name": field.name,
            "type": field.type,
            "values": list(field.values),
            **({"unit": field.unit} if field.unit else {}),
            **({"labels": field.labels} if field.labels else {}),
        }
        for field in frame.fields
    ]
    times = next((field["values"] for field in fields if field["type"] == "time"), None)
    end = max((value for value in times if isinstance(value, int | float)), default=None) if times else None
    meta: dict[str, Any] = {
        "interval": frame.meta.interval,
        "date_from": frame.meta.date_from.isoformat() if frame.meta.date_from else None,
        "date_to": frame.meta.date_to.isoformat() if frame.meta.date_to else None,
        "end": end,
    }
    if frame.meta.previous:
        meta["previous"] = True
    if frame.meta.truncated:
        meta["truncated"] = True
    # Encoded as the response encodes it, so a fresh Decimal and the float a cache hit reads back hash alike.
    content = orjson.dumps(
        {"name": frame.name, "labels": frame.labels, "fields": fields},
        default=JSONEncoder().default,
        option=orjson.OPT_SORT_KEYS | orjson.OPT_UTC_Z,
    )
    return {
        "name": frame.name,
        "labels": frame.labels,
        "fields": fields,
        "meta": meta,
        "hash": hashlib.sha256(content).hexdigest()[:16],
    }


# Trends, ported from PR #138426.


def trends_frames(query: TrendsQuery, result: Mapping[str, Any]) -> Optional[list[Frame]]:
    rows = result.get("results")
    if not isinstance(rows, list):
        return None
    display = query.trendsFilter.display if query.trendsFilter else None
    if display in _AGGREGATED_DISPLAYS:
        return trends_aggregated_frames(query, result)
    if display not in _TIME_SERIES_DISPLAYS:
        return None
    timezone = ZoneInfo(result.get("timezone") or "UTC")
    interval = query.interval.value if query.interval else "day"
    current = _meta(result.get("resolved_date_range"), interval, previous=False)
    previous = _meta(result.get("resolved_compare_date_range"), interval, previous=True)
    trends_filter = query.trendsFilter
    has_formula = bool(
        trends_filter and (trends_filter.formula or trends_filter.formulas or trends_filter.formulaNodes)
    )
    action_names = {int(key): name for key, name in (result.get("action_names") or {}).items() if str(key).isdigit()}
    frames: list[Frame] = []
    for index, series in enumerate(rows):
        is_previous = series.get("compare_label") == "previous"
        name = _trends_series_name(series, query, action_names, has_formula)
        frames.append(
            Frame(
                name=f"{name} (previous)" if is_previous else name,
                labels=_trends_series_labels(series, index),
                fields=[
                    FrameField(name="time", type="time", values=_wall_clock_ms(series["days"], timezone)),
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


def trends_aggregated_frames(query: TrendsQuery, result: Mapping[str, Any]) -> list[Frame]:
    """A number, pie, table, bar-value or map display: one frame per series and breakdown value, holding one number."""
    trends_filter = query.trendsFilter
    has_formula = bool(
        trends_filter and (trends_filter.formula or trends_filter.formulas or trends_filter.formulaNodes)
    )
    action_names = {int(key): name for key, name in (result.get("action_names") or {}).items() if str(key).isdigit()}
    current = _meta(result.get("resolved_date_range"), None, previous=False)
    previous = _meta(result.get("resolved_compare_date_range"), None, previous=True)
    frames: list[Frame] = []
    for index, series in enumerate(result["results"]):
        is_previous = series.get("compare_label") == "previous"
        name = _trends_series_name(series, query, action_names, has_formula)
        frames.append(
            Frame(
                name=f"{name} (previous)" if is_previous else name,
                labels=_trends_series_labels(series, index),
                fields=[FrameField(name="value", type="number", values=[series.get("aggregated_value")])],
                meta=previous if is_previous else current,
            )
        )
    return frames


# Stickiness, lifecycle, funnels and retention, with the numbers their insight charts draw.


def stickiness_frames(result: Mapping[str, Any]) -> Optional[list[Frame]]:
    """One frame per series: how many actors did it on exactly N intervals, so the x field is a count, not a time."""
    rows = result.get("results")
    if not isinstance(rows, list):
        return None
    frames: list[Frame] = []
    for index, series in enumerate(rows):
        is_previous = series.get("compare_label") == "previous"
        name = series.get("custom_name") or _readable_breakdown(str(series.get("label") or ""))
        frames.append(
            Frame(
                name=f"{name} (previous)" if is_previous else name,
                labels=_trends_series_labels(series, index),
                fields=[
                    FrameField(name="intervals", type="number", values=list(series.get("days") or [])),
                    FrameField(name="value", type="number", values=list(series.get("data") or [])),
                ],
                meta=FrameMeta(previous=is_previous),
            )
        )
    return frames


def lifecycle_frames(
    source: Mapping[str, Any], result: Mapping[str, Any], timezone_name: Optional[str] = None
) -> Optional[list[Frame]]:
    """One time series per status (new, returning, resurrecting, dormant). Dormant counts are negative, as charted."""
    rows = result.get("results")
    if not isinstance(rows, list):
        return None
    timezone = ZoneInfo(result.get("timezone") or timezone_name or "UTC")
    meta = _meta(result.get("resolved_date_range"), source.get("interval") or "day", previous=False)
    frames: list[Frame] = []
    for index, series in enumerate(rows):
        labels = _trends_series_labels(series, index)
        if series.get("status"):
            labels["status"] = str(series["status"])
        frames.append(
            Frame(
                name=series.get("label"),
                labels=labels,
                fields=[
                    FrameField(name="time", type="time", values=_wall_clock_ms(series.get("days") or [], timezone)),
                    FrameField(name="value", type="number", values=list(series.get("data") or [])),
                ],
                meta=meta,
            )
        )
    return frames


def funnels_frames(
    source: Mapping[str, Any], result: Mapping[str, Any], timezone_name: Optional[str] = None
) -> Optional[list[Frame]]:
    rows = result.get("results")
    if isinstance(rows, Mapping):
        return _funnel_time_to_convert_frames(rows)
    if not isinstance(rows, list):
        return None
    if not rows:
        return []
    series = source.get("series") or []
    optional = {
        index for index, node in enumerate(series) if isinstance(node, Mapping) and node.get("optionalInFunnel")
    }
    if isinstance(rows[0], list):
        return [_funnel_steps_frame(steps, optional) for steps in rows]
    if isinstance(rows[0], Mapping) and "bins" in rows[0]:
        # A compared time-to-convert funnel: one histogram per period.
        frames: list[Frame] = []
        for histogram in rows:
            period_frames = _funnel_time_to_convert_frames(histogram)
            if period_frames is None:
                return None
            frames.extend(period_frames)
        return frames
    if isinstance(rows[0], Mapping) and "days" in rows[0]:
        return _funnel_trends_frames(source, result, rows, timezone_name)
    # A compared funnel tags each step with its period. Rates are only meaningful within one period.
    periods: dict[Optional[str], list[Mapping[str, Any]]] = {}
    for step in rows:
        periods.setdefault(step.get("compare_label"), []).append(step)
    return [_funnel_steps_frame(steps, optional) for steps in periods.values()]


def _funnel_steps_frame(steps: Sequence[Mapping[str, Any]], optional: frozenset[int] | set[int] = frozenset()) -> Frame:
    """One row per step, with the conversion rates the funnel chart shows: from the first step and from the previous."""
    counts = [step.get("count") or 0 for step in steps]
    first = counts[0] if counts else 0
    # Like the funnel chart, a step converts from the last required step before it, skipping optional ones.
    step_rates: list[Optional[float]] = []
    last_required = 0
    for index, count in enumerate(counts):
        step_rates.append(_percent(count, counts[last_required] if index else count))
        if index not in optional:
            last_required = index
    labels: dict[str, str] = {}
    breakdown_value = steps[0].get("breakdown_value") if steps else None
    if breakdown_value is not None:
        labels["breakdown_value"] = _breakdown_label(breakdown_value)
    is_previous = bool(steps) and steps[0].get("compare_label") == "previous"
    name = labels.get("breakdown_value")
    if is_previous:
        name = f"{name} (previous)" if name else "previous"
    return Frame(
        name=name,
        labels=labels,
        fields=[
            FrameField(
                name="step", type="string", values=[step.get("custom_name") or step.get("name") for step in steps]
            ),
            FrameField(name="count", type="number", values=counts),
            FrameField(name="conversion_rate", type="number", values=[_percent(count, first) for count in counts]),
            FrameField(
                name="step_conversion_rate",
                type="number",
                values=step_rates,
            ),
            FrameField(
                name="average_conversion_time",
                type="number",
                values=[step.get("average_conversion_time") for step in steps],
                unit="s",
            ),
            FrameField(
                name="median_conversion_time",
                type="number",
                values=[step.get("median_conversion_time") for step in steps],
                unit="s",
            ),
        ],
        meta=FrameMeta(previous=is_previous),
    )


def _percent(part: float, whole: float) -> Optional[float]:
    return part / whole * 100 if whole else None


def _funnel_trends_frames(
    source: Mapping[str, Any],
    result: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    timezone_name: Optional[str] = None,
) -> list[Frame]:
    # The runner already gives each day's conversion as a percentage.
    timezone = ZoneInfo(result.get("timezone") or timezone_name or "UTC")
    interval = source.get("interval") or "day"
    current = _meta(result.get("resolved_date_range"), interval, previous=False)
    previous = FrameMeta(interval=interval, previous=True)
    frames: list[Frame] = []
    for row in rows:
        breakdown_value = row.get("breakdown_value")
        labels = {} if breakdown_value is None else {"breakdown_value": _breakdown_label(breakdown_value)}
        is_previous = row.get("compare_label") == "previous"
        name = labels.get("breakdown_value", "conversion")
        frames.append(
            Frame(
                name=f"{name} (previous)" if is_previous else name,
                labels=labels,
                fields=[
                    FrameField(name="time", type="time", values=_wall_clock_ms(row.get("days") or [], timezone)),
                    FrameField(name="conversion_rate", type="number", values=list(row.get("data") or [])),
                ],
                meta=previous if is_previous else current,
            )
        )
    return frames


def _funnel_time_to_convert_frames(histogram: Mapping[str, Any]) -> Optional[list[Frame]]:
    bins = histogram.get("bins")
    if not isinstance(bins, list):
        return None
    is_previous = histogram.get("compare_label") == "previous"
    return [
        Frame(
            name="time to convert (previous)" if is_previous else "time to convert",
            labels={},
            fields=[
                FrameField(name="seconds", type="number", values=[bin[0] for bin in bins], unit="s"),
                FrameField(name="count", type="number", values=[bin[1] for bin in bins]),
            ],
            meta=FrameMeta(previous=is_previous),
        )
    ]


def retention_frames(result: Mapping[str, Any]) -> Optional[list[Frame]]:
    """The retention table: one row per cohort, its start time and one count per period. One frame per breakdown value."""
    rows = result.get("results")
    if not isinstance(rows, list):
        return None
    # Grouped by the raw value: a literal "Other" and the overflow bucket share a display label but are different cohorts.
    groups: dict[str, tuple[Any, list[Mapping[str, Any]]]] = {}
    for row in rows:
        raw = row.get("breakdown_value")
        groups.setdefault(json.dumps(raw, sort_keys=True, default=str), (raw, []))[1].append(row)
    frames: list[Frame] = []
    for raw_breakdown, cohorts in groups.values():
        breakdown_value = None if raw_breakdown is None else _breakdown_label(raw_breakdown)
        periods = max((len(cohort.get("values") or []) for cohort in cohorts), default=0)
        widest = max(cohorts, key=lambda cohort: len(cohort.get("values") or []))
        period_names = [value.get("label") or f"Period {index}" for index, value in enumerate(widest["values"] or [])]
        labels = {} if breakdown_value is None else {"breakdown_value": breakdown_value}
        frames.append(
            Frame(
                name=breakdown_value,
                labels=labels,
                fields=[
                    FrameField(name="cohort", type="time", values=[_time_ms(cohort.get("date")) for cohort in cohorts]),
                    *(
                        FrameField(
                            name=period_names[period],
                            type="number",
                            values=[_period_count(cohort, period) for cohort in cohorts],
                        )
                        for period in range(periods)
                    ),
                ],
                meta=FrameMeta(),
            )
        )
    return frames


def _period_count(cohort: Mapping[str, Any], period: int) -> Optional[float]:
    # With a sum or avg aggregation the chart shows the aggregated property, not the actor count.
    values = cohort.get("values") or []
    if period >= len(values):
        return None
    value = values[period]
    aggregated = value.get("aggregation_value")
    return aggregated if aggregated is not None else value.get("count")


# Any other runner: a table with columns, or a list of records.

_WEB_COLUMN_PREFIX = "context.columns."


def table_frames(kind: str, result: Mapping[str, Any]) -> Optional[list[Frame]]:
    """A runner's rows as one table frame, never pivoted: an events list or a web analytics table is not a series."""
    rows = result.get("results")
    if not isinstance(rows, list):
        return None
    if isinstance(result.get("columns"), list) and all(isinstance(row, list | tuple) for row in rows):
        table = _web_table(result) if kind.startswith("Web") else result
        return hogql_frames(table, pivot=False)
    if all(isinstance(row, Mapping) for row in rows):
        if not _records_fit(rows):
            return None
        return [records_frame(rows, truncated=result.get("hasMore") is True)] if rows else []
    return None


def _records_fit(rows: Sequence[Mapping[str, Any]]) -> bool:
    names: set[Any] = set()
    for row in rows:
        names.update(row)
        if len(names) > MAX_RECORD_FIELDS or len(names) * len(rows) > MAX_RECORD_CELLS:
            return False
    return True


def _web_table(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Web analytics columns are named `context.columns.<name>`, and a compared number is a `[current, previous]` pair.
    The pair becomes two number columns, `<name>` and `<name> (previous)`."""
    columns = [str(column).removeprefix(_WEB_COLUMN_PREFIX) for column in result["columns"]]
    rows = result["results"]
    pairs = [
        column != "breakdown_value" and _is_compared_pair_column(rows, index) for index, column in enumerate(columns)
    ]
    types = list(result.get("types") or [])
    new_columns: list[str] = []
    new_types: list[Any] = []
    for index, column in enumerate(columns):
        if pairs[index]:
            new_columns.extend([column, f"{column} (previous)"])
            new_types.extend(["Float64", "Float64"])
        else:
            new_columns.append(column)
            new_types.append(types[index] if index < len(types) else "")
    new_rows: list[list[Any]] = []
    for row in rows:
        new_row: list[Any] = []
        for index, value in enumerate(row):
            if index < len(pairs) and pairs[index]:
                new_row.extend(value if value is not None else [None, None])
            else:
                new_row.append(value)
        new_rows.append(new_row)
    return {**result, "columns": new_columns, "types": new_types, "results": new_rows}


def _is_compared_pair_column(rows: Sequence[Sequence[Any]], index: int) -> bool:
    """A breakdown dimension can also be a number pair (a viewport is `[width, height]`), so only metric columns split,
    and only when at least one row actually holds a pair."""
    values = [row[index] for row in rows if index < len(row) and row[index] is not None]
    return bool(values) and all(
        isinstance(value, list | tuple) and len(value) == 2 and _is_number_or_none(value) for value in values
    )


def _is_number_or_none(values: Sequence[Any]) -> bool:
    return all(value is None or (isinstance(value, int | float) and not isinstance(value, bool)) for value in values)


def records_frame(rows: Sequence[Mapping[str, Any]], *, truncated: bool = False) -> Frame:
    """A list of objects (a web overview, paths' links...) as a table: one field per key, in first-seen order."""
    names: dict[str, None] = {}
    for row in rows:
        names.update(dict.fromkeys(str(key) for key in row))
    fields: list[FrameField] = []
    for name in names:
        values = [row.get(name) for row in rows]
        sample = next((value for value in values if value is not None), None)
        field_type: FrameFieldType
        if isinstance(sample, bool):
            field_type = "boolean"
        elif isinstance(sample, int | float):
            field_type = "number"
        elif isinstance(sample, str) or sample is None:
            field_type = "string"
        else:
            field_type = "other"
        fields.append(FrameField(name=name, type=field_type, values=values))
    return Frame(name=None, labels={}, fields=fields, meta=FrameMeta(truncated=truncated))


# Metrics (builder, SQL and PromQL), ported from PR #138426.


def metrics_frames(result: Mapping[str, Any]) -> Optional[list[Frame]]:
    series_list = result.get("results")
    if not isinstance(series_list, list):
        return None
    # The runner can coarsen the query's interval and the response does not say to what, so no interval is given.
    meta = _meta(result.get("resolved_date_range"), None, previous=False)
    # Same naming as the metrics chart (metricsSeries.ts formatSeriesNames).
    several_clauses = len({series.get("clause") for series in series_list if series.get("clause")}) > 1
    frames: list[Frame] = []
    for series in series_list:
        labels: dict[str, str] = series.get("labels") or {}
        prefix = f"{series['clause']} · " if several_clauses and series.get("clause") else ""
        name = ", ".join(f"{key}={value}" for key, value in labels.items()) if labels else None
        points = series.get("points") or []
        frames.append(
            Frame(
                name=prefix + (name or series.get("metricName") or series.get("clause") or "value"),
                labels=labels,
                fields=[
                    FrameField(
                        name="time", type="time", values=[_epoch_ms(_datetime(point["time"])) for point in points]
                    ),
                    FrameField(
                        name="value",
                        type="number",
                        values=[point["value"] for point in points],
                        unit=series.get("unit"),
                    ),
                ],
                meta=meta,
            )
        )
    return frames


# Prometheus API results (a LogQL metric query), ported from Dash's promToFrames and streamsToFrames.


def prometheus_frames(data: Mapping[str, Any]) -> Optional[list[Frame]]:
    result_type = data.get("resultType")
    results = data.get("result") or []
    if result_type == "streams":
        frame = streams_frame(results)
        return [frame] if frame else None
    if result_type not in ("matrix", "vector") or len(results) > MAX_PROMETHEUS_SERIES:
        return None
    frames: list[Frame] = []
    for index, series in enumerate(results):
        labels = {key: str(value) for key, value in (series.get("metric") or {}).items() if key != "__name__"}
        pairs = [series["value"]] if result_type == "vector" else (series.get("values") or [])
        frames.append(
            Frame(
                name=_default_series_name(labels, index),
                labels=labels,
                fields=[
                    FrameField(name="time", type="time", values=[int(float(time) * 1000) for time, _ in pairs]),
                    FrameField(name="value", type="number", values=[_prometheus_value(value) for _, value in pairs]),
                ],
                meta=FrameMeta(),
            )
        )
    return frames


def _prometheus_value(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _default_series_name(labels: Mapping[str, str], index: int) -> str:
    # Grafana's default: one label is its value, several are `k=v` pairs.
    if len(labels) == 1:
        return next(iter(labels.values()))
    if labels:
        return ", ".join(f"{key}={value}" for key, value in labels.items())
    return "value" if index == 0 else f"series {index + 1}"


def streams_frame(streams: Sequence[Mapping[str, Any]]) -> Optional[Frame]:
    """Log lines as one table frame, newest first: time, line and the stream's labels.

    None when the labels repeated on every line would pass MAX_STREAM_LABEL_BYTES.
    """
    rows: list[tuple[int, str, str]] = []
    label_bytes = 0
    for stream in streams:
        labels = " ".join(f"{key}={value}" for key, value in (stream.get("stream") or {}).items())
        values = stream.get("values") or []
        label_bytes += len(labels.encode()) * len(values)
        if label_bytes > MAX_STREAM_LABEL_BYTES:
            return None
        for nanoseconds, line in values:
            rows.append((int(nanoseconds), str(line), labels))
    # Sorted on nanoseconds, so two lines in the same millisecond keep their order.
    rows.sort(key=lambda row: row[0], reverse=True)
    return Frame(
        name=None,
        labels={},
        fields=[
            FrameField(name="time", type="time", values=[row[0] // 1_000_000 for row in rows]),
            FrameField(name="line", type="string", values=[row[1] for row in rows]),
            FrameField(name="labels", type="string", values=[row[2] for row in rows]),
        ],
        meta=FrameMeta(),
    )


# HogQL tables, ported from Dash's hogqlToFrames, unwrapHx and pivotLong.


def hogql_frames(result: Mapping[str, Any], *, pivot: bool = True) -> Optional[list[Frame]]:
    if not isinstance(result.get("results"), list):
        return None
    table = unwrap_html_tags(
        HogQLTable(
            columns=list(result.get("columns") or []), types=list(result.get("types") or []), rows=result["results"]
        )
    )
    columns, types, rows = table.columns, table.types, table.rows
    fields: list[FrameField] = []
    for index, name in enumerate(columns):
        raw = types[index] if index < len(types) else None
        # PostHog sends types as [name, type] pairs. Reading the pair as one string made a column named "intent" a number.
        type_name = str(raw[1] if isinstance(raw, list | tuple) and len(raw) > 1 else (raw or ""))
        sample = next((row[index] for row in rows if row[index] is not None), None)
        field_type: FrameFieldType
        if _COMPOUND_TYPE.match(type_name) or isinstance(sample, list | tuple | dict):
            field_type = "other"
        elif _ENUM_TYPE.match(type_name):
            field_type = "string"
        elif _TIME_TYPE.search(type_name):
            field_type = "time"
        elif _NUMBER_TYPE.search(type_name) or (isinstance(sample, int | float) and not isinstance(sample, bool)):
            field_type = "number"
        elif "bool" in type_name.lower():
            field_type = "boolean"
        else:
            field_type = "string"
        values = [row[index] for row in rows]
        if field_type == "time":
            values = [_time_ms(value) for value in values]
        fields.append(
            FrameField(
                name=name,
                type=field_type,
                values=values,
                # A calendar date is that day, not a moment to shift into the viewer's timezone.
                unit="date" if field_type == "time" and _DATE_ONLY_TYPE.match(type_name) else None,
            )
        )
    frame = Frame(name=None, labels={}, fields=fields, meta=FrameMeta(truncated=result.get("hasMore") is True))
    return pivot_long(frame) if pivot else [frame]


def pivot_long(frame: Frame) -> list[Frame]:
    """Long to wide, like Grafana's SQL datasources: `SELECT t, client, count()` (one time column, string columns,
    number columns) becomes one frame per distinct string combination, in first-seen order, so `ORDER BY n DESC`
    puts the biggest series first. Any other table comes back as it is."""
    times = [field for field in frame.fields if field.type == "time"]
    strings = [field for field in frame.fields if field.type == "string"]
    numbers = [field for field in frame.fields if field.type == "number"]
    if len(times) != 1 or not strings or not numbers or len(times) + len(strings) + len(numbers) != len(frame.fields):
        return [frame]
    [time] = times
    groups: dict[tuple[Optional[str], ...], list[int]] = {}
    label_names = [field.name for field in strings]
    # Every series repeats the time and number column names too.
    repeated_names = sum(len(field.name.encode()) for field in (time, *numbers))
    label_bytes = 0
    for row in range(len(time.values)):
        key = tuple(None if field.values[row] is None else str(field.values[row]) for field in strings)
        if key not in groups:
            if len(groups) >= MAX_PIVOT_SERIES or (len(groups) + 1) * (len(numbers) + 1) > MAX_PIVOT_FIELDS:
                return [frame]
            label_bytes += (
                sum(len(name.encode()) + len((value or _NO_LABEL).encode()) for name, value in zip(label_names, key))
                * (len(numbers) + 1)
                + repeated_names
            )
            if label_bytes > MAX_PIVOT_LABEL_BYTES:
                return [frame]
            groups[key] = []
        groups[key].append(row)
    frames: list[Frame] = []
    for key, rows in groups.items():
        values = [_label_value(value) for value in key]
        labels = {field.name: value for field, value in zip(strings, values)}
        frames.append(
            Frame(
                name=" / ".join(values),
                labels=labels,
                fields=[
                    FrameField(name=time.name, type="time", values=[time.values[row] for row in rows], unit=time.unit),
                    *(
                        FrameField(
                            name=field.name, type="number", values=[field.values[row] for row in rows], labels=labels
                        )
                        for field in numbers
                    ),
                ],
                meta=frame.meta,
            )
        )
    return frames


def _label_value(value: Any) -> str:
    return _NO_LABEL if value is None else str(value)


@frozen
class HogQLTable:
    columns: list[str]
    # PostHog's `[name, type]` pairs, one per column.
    types: list[Any]
    rows: list[list[Any]]


def unwrap_html_tags(table: HogQLTable) -> HogQLTable:
    """HogQL's HTML tags (`<a href=...>Jul 2026</a>` in a SELECT) come back as `["__hx_tag", "a", key, value...,
    "children", [...]]`. A tagged column becomes its text, and a link column gets a `<column> (link)` column beside it."""
    columns, types, rows = table.columns, table.types, table.rows
    tagged = [any(_tag_text(row[index]) is not None for row in rows) for index in range(len(columns))]
    if not any(tagged):
        return table
    linked = [tagged[index] and any(_tag_href(row[index]) for row in rows) for index in range(len(columns))]
    new_columns: list[str] = []
    new_types: list[Any] = []
    for index, name in enumerate(columns):
        new_columns.append(name)
        if types:
            new_types.append([name, "String"] if tagged[index] else types[index])
        if linked[index]:
            new_columns.append(f"{name} (link)")
            if types:
                new_types.append([f"{name} (link)", "String"])
    new_rows: list[list[Any]] = []
    for row in rows:
        new_row: list[Any] = []
        for index, value in enumerate(row):
            text = _tag_text(value) if tagged[index] else None
            new_row.append(value if text is None else text)
            if linked[index]:
                new_row.append(_tag_href(value))
        new_rows.append(new_row)
    return HogQLTable(columns=new_columns, types=new_types, rows=new_rows)


def _is_tag(value: Any) -> bool:
    # A fresh result holds tags as tuples, and a cached one, read back from JSON, as lists.
    return isinstance(value, list | tuple) and bool(value) and value[0] == "__hx_tag"


def _tag_attribute(value: Sequence[Any], key: str) -> tuple[bool, Any]:
    # After the marker and the tag name come key/value pairs, so a value that reads "href" is never taken for a key.
    for position in range(2, len(value) - 1, 2):
        if value[position] == key:
            return True, value[position + 1]
    return False, None


def _tag_text(value: Any) -> Optional[str]:
    if not _is_tag(value):
        return None
    found, children = _tag_attribute(value, "children")
    return _children_text(children) if found else ""


def _children_text(children: Any) -> str:
    # Children are a tag, a list of parts, or HogQL's f-string `["f", part...]`, whose parts are joined.
    if isinstance(children, list | tuple):
        if _is_tag(children):
            return _tag_text(children) or ""
        parts = children[1:] if children and children[0] == "f" else children
        return "".join(_children_text(part) for part in parts)
    return "" if children is None else str(children)


def _tag_href(value: Any) -> Optional[str]:
    if _is_tag(value) and len(value) > 1 and value[1] == "a":
        found, href = _tag_attribute(value, "href")
        return str(href) if found else None
    return None


def _time_ms(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return _epoch_ms(value if value.tzinfo else value.replace(tzinfo=dt.UTC))
    if isinstance(value, dt.date):
        return _epoch_ms(dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC))
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return value
        return _epoch_ms(parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC))
    return value


def _meta(date_range: Optional[Mapping[str, Any]], interval: Optional[str], *, previous: bool) -> FrameMeta:
    return FrameMeta(
        interval=interval,
        date_from=_datetime(date_range["date_from"]) if date_range and date_range.get("date_from") else None,
        date_to=_datetime(date_range["date_to"]) if date_range and date_range.get("date_to") else None,
        previous=previous,
    )


def _datetime(value: dt.datetime | str) -> dt.datetime:
    return value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)


def _wall_clock_ms(days: Sequence[str], timezone: ZoneInfo) -> list[int]:
    # Trends buckets are wall-clock times in the project's timezone, without an offset. When the clocks go back, the
    # repeated hour comes round a second time, so a time earlier than one already seen is the later of the two.
    times: list[int] = []
    latest: Optional[dt.datetime] = None
    for day in days:
        wall_clock = dt.datetime.fromisoformat(day)
        repeated = latest is not None and wall_clock <= latest
        times.append(_epoch_ms(wall_clock.replace(tzinfo=timezone, fold=1 if repeated else 0)))
        latest = wall_clock if latest is None or wall_clock > latest else latest
    return times


def _epoch_ms(value: dt.datetime) -> int:
    return int(value.timestamp() * 1000)


# Traces. Span durations arrive in nanoseconds and leave in milliseconds, the unit the charts' duration axis reads.

_NANOS_PER_MS = 1_000_000
# (field, row key, unit). The first is the one a bar chart draws, so an operations chart ranks by traffic.
_SPAN_AGGREGATE_FIELDS: tuple[tuple[str, str, Optional[str]], ...] = (
    ("count", "count", None),
    ("error_count", "error_count", None),
    ("error_rate", "error_rate", "%"),
    ("avg_duration", "avg_duration_nano", "ms"),
    ("p50_duration", "p50_duration_nano", "ms"),
    ("p95_duration", "p95_duration_nano", "ms"),
    ("p99_duration", "p99_duration_nano", "ms"),
    ("sessions", "sessions", None),
    ("users", "users", None),
)


def span_aggregation_frames(result: Mapping[str, Any], *, as_table: bool = False) -> Optional[list[Frame]]:
    """A span aggregation as one series per operation, each a single point at the end of the window, so a bar chart
    draws one bar per operation. As a table, one frame with a row per operation. The comparison window is left out.

    A number the result does not carry, such as `sessions` without `includeImpact`, is left out rather than drawn as 0.
    """
    rows = result.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        return None
    columns: list[tuple[str, Optional[str], list[Optional[float]]]] = []
    for name, key, unit in _SPAN_AGGREGATE_FIELDS:
        values = [_span_aggregate(row, key) for row in rows]
        if any(value is not None for value in values):
            columns.append((name, unit, values))
    date_range = result.get("resolved_date_range")
    meta = _meta(date_range if isinstance(date_range, Mapping) else None, None, previous=False)
    services = [str(row.get("service_name") or "") for row in rows]
    operations = [str(row.get("name") or "") for row in rows]
    # Each series repeats its labels in its name, its labels and every number field, so long span names stay a table.
    label_bytes = sum(
        (len(service.encode()) + len(operation.encode())) * (len(columns) + 2)
        for service, operation in zip(services, operations)
    )
    if as_table or meta.date_to is None or len(rows) > MAX_PIVOT_SERIES or label_bytes > MAX_PIVOT_LABEL_BYTES:
        return [
            Frame(
                name=None,
                labels={},
                fields=[
                    FrameField(name="service", type="string", values=services),
                    FrameField(name="operation", type="string", values=operations),
                    *(FrameField(name=name, type="number", values=values, unit=unit) for name, unit, values in columns),
                ],
                meta=meta,
            )
        ]
    end = _epoch_ms(meta.date_to)
    frames: list[Frame] = []
    for index, (service, operation) in enumerate(zip(services, operations)):
        labels = {"service": service, "operation": operation}
        frames.append(
            Frame(
                name=f"{service} / {operation}" if service else operation,
                labels=labels,
                fields=[
                    FrameField(name="time", type="time", values=[end]),
                    *(
                        FrameField(name=name, type="number", values=[values[index]], unit=unit, labels=labels)
                        for name, unit, values in columns
                    ),
                ],
                meta=meta,
            )
        )
    return frames


def _span_aggregate(row: Mapping[str, Any], key: str) -> Optional[float]:
    if key == "error_rate":
        count, errors = row.get("count"), row.get("error_count")
        if not isinstance(count, int | float) or not isinstance(errors, int | float) or not count:
            return None
        return 100 * errors / count
    value = row.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return value / _NANOS_PER_MS if key.endswith("_nano") else value


def span_list_frames(result: Mapping[str, Any]) -> Optional[list[Frame]]:
    """Spans as one table frame, a row per span in the runner's order."""
    rows = result.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        return None

    def column(key: str) -> list[Any]:
        return [row.get(key) for row in rows]

    return [
        Frame(
            name=None,
            labels={},
            fields=[
                FrameField(name="time", type="time", values=[_time_ms(value) for value in column("timestamp")]),
                FrameField(name="service", type="string", values=column("service_name")),
                FrameField(name="operation", type="string", values=column("name")),
                FrameField(
                    name="duration",
                    type="number",
                    values=[
                        value / _NANOS_PER_MS if isinstance(value, int | float) else None
                        for value in column("duration_nano")
                    ],
                    unit="ms",
                ),
                FrameField(name="status_code", type="number", values=column("status_code")),
                FrameField(name="kind", type="number", values=column("kind")),
                FrameField(name="is_root_span", type="boolean", values=column("is_root_span")),
                FrameField(name="trace_id", type="string", values=column("trace_id")),
                FrameField(name="span_id", type="string", values=column("span_id")),
            ],
            meta=FrameMeta(truncated=result.get("hasMore") is True),
        )
    ]
