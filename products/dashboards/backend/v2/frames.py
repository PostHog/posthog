"""Query batch results as chart-ready frames, so a chart draws any target without knowing its language.

A frame is Dash's `DataFrame` (packages/schema/src/frame.ts in PostHog/dash): a name, labels, a time field in epoch
milliseconds, one or more value fields and meta. Each language's result has one converter here. A result whose kind has
no frame shape (funnels, retention, paths...) gets None, and its line keeps the raw result.

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
# A log table repeats its stream's labels on every line. Above this many label bytes, the result stays raw.
MAX_STREAM_LABEL_BYTES = 8 * 1024 * 1024
# Each Prometheus series becomes a frame of its own, many times the size of the series in the response. Above this
# many series, the result stays raw.
MAX_PROMETHEUS_SERIES = 1000


def frames_for(
    language: QueryBatchLanguage,
    query: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    legend: Optional[str] = None,
    target_format: Optional[QueryBatchTargetFormat] = None,
) -> Optional[list[dict[str, Any]]]:
    """The frames of one query batch result as JSON, or None when its kind has no frame shape.

    `query` is the query node that ran, or for LogQL nothing. `result` is the runner's response as a dict.
    """
    frames = _frames(language, query, result, target_format)
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
    if kind == "MetricsQuery":
        return metrics_frames(result)
    if kind == "TrendsQuery":
        try:
            return trends_frames(TrendsQuery.model_validate(source), result)
        except ValidationError:
            return None
    return None


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
    if (query.trendsFilter.display if query.trendsFilter else None) not in _TIME_SERIES_DISPLAYS:
        return None
    rows = result.get("results")
    if not isinstance(rows, list):
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
