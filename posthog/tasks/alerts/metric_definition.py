"""Plain-English rendering of the alerted insight's query definition.

Without this a model only sees the insight's *name* plus the numbers, so a series
called "Error tracking active users" reads as a count of
people hitting errors even when it is a `$pageview` DAU series filtered to a set
of app URLs, and the model then reaches for an outage to explain an engagement
change. Naming the event, aggregation, and filters the alerted series is built
from keeps every hypothesis tied to what the number actually measures.

Deliberately dependency-light (stdlib only): it renders the stored query dict
rather than routing through HogQL machinery, which must stay off the Temporal
workflow module's import path.
"""

from __future__ import annotations

import re
import json
from typing import Any

import structlog

from posthog.dataclasses import frozen


@frozen
class MetricDateRange:
    start: str
    end: str


logger = structlog.get_logger(__name__)

# The block is prompt context, so it is capped rather than trusting query size —
# a query can carry hundreds of filter values.
MAX_DEFINITION_CHARS = 2500
MAX_DESCRIBED_SERIES = 6
MAX_DESCRIBED_FORMULAS = 4
MAX_DESCRIBED_FILTERS = 8
MAX_VALUE_CHARS = 120
MAX_SQL_CHARS = 800
# Property groups nest (AND of ORs); anything deeper is malformed rather than real.
MAX_FILTER_DEPTH = 4

UNAVAILABLE = (
    "Metric definition: unavailable — this insight's query could not be read. Do not infer what the "
    "metric counts from its name; check the underlying data with your tools before proposing a cause."
)

_WRAPPER_KINDS = frozenset({"InsightVizNode", "DataTableNode", "DataVisualizationNode"})

_MATH_LABELS = {
    "total": "total event count",
    "dau": "unique users (DAU)",
    "weekly_active": "weekly active users",
    "monthly_active": "monthly active users",
    "unique_session": "unique sessions",
    "first_time_for_user": "count of first-ever occurrences per user",
    "first_matching_event_for_user": "count of first matching occurrences per user",
}

_FILTER_SCOPE_LABELS = {
    "event": "event property",
    "event_metadata": "event metadata",
    "person": "person property",
    "element": "element",
    "session": "session property",
    "group": "group property",
    "feature": "feature flag",
    "hogql": "HogQL expression",
    "data_warehouse": "warehouse property",
    "data_warehouse_person_property": "warehouse person property",
    "recording": "recording property",
    "log_entry": "log entry property",
    "error_tracking_issue": "error tracking issue property",
}

_OPERATOR_LABELS = {
    "exact": "is",
    "is_not": "is not",
    "icontains": "contains",
    "not_icontains": "does not contain",
    "starts_with": "starts with",
    "not_starts_with": "does not start with",
    "ends_with": "ends with",
    "not_ends_with": "does not end with",
    "regex": "matches regex",
    "not_regex": "does not match regex",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "is_set": "is set",
    "is_not_set": "is not set",
    "in": "is one of",
    "not_in": "is not one of",
}

_VALUELESS_OPERATORS = frozenset({"is_set", "is_not_set"})


def describe_metric_definition(
    query: Any,
    *,
    series_index: int = 0,
    effective_date_range: MetricDateRange | None = None,
    alert_config: dict[str, Any] | None = None,
) -> str:
    """A plain-text block naming what the alerted series measures.

    ``effective_date_range`` is the span of the points the caller actually supplies, for
    readers that fetch a different range than the insight's saved one. Given it, the block
    describes that span instead of the saved range, which would otherwise contradict the
    dates alongside it.

    ``alert_config`` is the alert's per-insight-kind config. A SQL query can return several
    numeric columns in either time order, and only the config says which column the values
    are and which way the rows run.

    Never raises: this only enriches the agent's context, so an unrecognized or
    malformed query degrades to a "couldn't read it" line rather than failing an
    investigation that would otherwise have run.
    """
    try:
        described = _describe(query, series_index, effective_date_range, alert_config)
    except Exception:
        logger.warning("alerts.metric_definition_failed", exc_info=True)
        return UNAVAILABLE
    return described[:MAX_DEFINITION_CHARS]


def _describe(
    query: Any,
    series_index: int,
    effective_date_range: MetricDateRange | None = None,
    alert_config: dict[str, Any] | None = None,
) -> str:
    source = unwrap_query_source(query)
    if not source:
        return UNAVAILABLE

    kind = source.get("kind") or "unknown"
    lines = [f"Metric definition — what the alerted number is actually built from (query kind: {kind}):"]

    series = source.get("series")
    clauses = source.get("clauses")
    formulas = _formulas(source)
    if isinstance(series, list) and series and formulas:
        # With formulas, the alerted result is a formula over the series, and series_index
        # picks a formula, not a raw series. The alerted formula and its inputs come first:
        # the block is cut at a fixed size, and the other formulas are optional context.
        lines.append(_describe_alerted_formula(formulas, series_index))
        alerted = formulas[series_index][0] if 0 <= series_index < len(formulas) else ""
        lines.extend(_describe_series(series, series_index=None, keep=_formula_inputs(alerted)))
        lines.extend(_describe_other_formulas(formulas, series_index))
    elif isinstance(series, list) and series:
        lines.extend(_describe_series(series, series_index))
    elif isinstance(clauses, list) and clauses:
        lines.extend(_describe_clauses(clauses))
    elif source.get("query"):
        lines.append(f"- SQL: {_clip(str(source['query']), MAX_SQL_CHARS)}")
        lines.extend(_describe_sql_reading(alert_config))
    else:
        lines.append("- Series: could not be read from the stored query.")

    lines.extend(_describe_query_scope(source, effective_date_range))
    return "\n".join(lines)


def unwrap_query_source(query: Any) -> dict[str, Any] | None:
    """Peel InsightVizNode/DataTable/DataVisualization wrappers off the stored query."""
    current = query
    for _ in range(len(_WRAPPER_KINDS) + 1):
        if not isinstance(current, dict):
            return None
        source = current.get("source")
        if current.get("kind") in _WRAPPER_KINDS and isinstance(source, dict):
            current = source
            continue
        return current
    return None


def _formulas(source: dict[str, Any]) -> list[tuple[str, str | None]]:
    """Every formula on the query as (expression, custom name), across the three shapes the
    trends filter has carried: ``formulaNodes``, ``formulas``, and the single ``formula``."""
    trends_filter = source.get("trendsFilter")
    if not isinstance(trends_filter, dict):
        return []
    nodes = trends_filter.get("formulaNodes")
    if isinstance(nodes, list) and nodes:
        return [
            (str(node.get("formula") or ""), node.get("custom_name") or None)
            for node in nodes
            if isinstance(node, dict)
        ]
    formulas = trends_filter.get("formulas")
    if isinstance(formulas, list) and formulas:
        return [(str(formula), None) for formula in formulas]
    formula = trends_filter.get("formula")
    return [(str(formula), None)] if formula else []


def _describe_alerted_formula(formulas: list[tuple[str, str | None]], series_index: int) -> str:
    if 0 <= series_index < len(formulas):
        return _describe_formula(formulas[series_index], series_index, alerted=True)
    return f"- (The alerted result index {series_index} is past the {len(formulas)} formulas defined.)"


def _describe_other_formulas(formulas: list[tuple[str, str | None]], series_index: int) -> list[str]:
    """The lines for the formulas other than the alerted one, capped.

    Custom names are unbounded, so each is clipped and the other formulas are capped:
    otherwise one long name ahead of the alerted formula could push it past the block's cut.
    """
    others = [index for index in range(len(formulas)) if index != series_index]
    lines = [_describe_formula(formulas[index], index, alerted=False) for index in others[:MAX_DESCRIBED_FORMULAS]]
    if len(others) > MAX_DESCRIBED_FORMULAS:
        lines.append(f"- ({len(others) - MAX_DESCRIBED_FORMULAS} further formulas omitted.)")
    return lines


def _describe_formula(formula: tuple[str, str | None], index: int, *, alerted: bool) -> str:
    expression, name = formula
    named = f' named "{_clip(name, MAX_VALUE_CHARS)}"' if name else ""
    label = "Alerted result" if alerted else "Other result in this insight"
    placement = "below" if alerted else "above"
    return (
        f"- {label} (index {index}): formula {_clip(expression, MAX_VALUE_CHARS)}{named}, "
        f"combining the input series {placement} by letter (A is the first input series)"
    )


def _describe_sql_reading(alert_config: dict[str, Any] | None) -> list[str]:
    """Which column the values come from and which way the rows run, for a SQL alert."""
    if not isinstance(alert_config, dict) or alert_config.get("type") != "HogQLAlertConfig":
        return []
    column = alert_config.get("column")
    lines = [
        f'- Alerted values: column "{_clip(str(column), MAX_VALUE_CHARS)}"'
        if column
        else "- Alerted values: the query's single numeric column"
    ]
    label_column = alert_config.get("label_column")
    if label_column:
        lines.append(f'- Point labels: column "{_clip(str(label_column), MAX_VALUE_CHARS)}"')
    evaluation = alert_config.get("evaluation")
    if evaluation == "first_row":
        lines.append(
            "- Row order: the query returns newest first; the rows were reversed, so the last value is the latest"
        )
    elif evaluation == "last_row":
        lines.append("- Row order: the query returns oldest first; the last value is the latest")
    return lines


def _formula_inputs(expression: str) -> list[int]:
    """The series indices a formula refers to by letter: A is 0, Z is 25, AA is 26."""
    indices: list[int] = []
    for letters in re.findall(r"(?<![A-Za-z])([A-Z]{1,2})(?![A-Za-z])", expression):
        index = 0
        for letter in letters:
            index = index * 26 + (ord(letter) - ord("A") + 1)
        indices.append(index - 1)
    return indices


def _describe_series(series: list[Any], series_index: int | None, keep: list[int] | None = None) -> list[str]:
    described = list(range(min(len(series), MAX_DESCRIBED_SERIES)))
    # The cap bounds the prompt, but the alerted series, or the inputs of the alerted formula,
    # are what the judge is asked about, so they displace capped ones rather than being omitted.
    wanted = [i for i in ([series_index] if series_index is not None else []) + (keep or []) if i < len(series)]
    slot = len(described) - 1
    for index in dict.fromkeys(wanted):
        if index in described:
            continue
        while slot >= 0 and described[slot] in wanted:
            slot -= 1
        if slot < 0:
            break
        described[slot] = index
        slot -= 1
    lines: list[str] = []
    for index in described:
        if series_index is None:
            label = f"Input series {chr(ord('A') + index)}" if index < 26 else "Input series"
        else:
            label = "Alerted series" if index == series_index else "Other series in this insight"
        lines.append(f"- {label} (index {index}): {_describe_series_node(series[index])}")
    if len(series) > len(described):
        lines.append(f"- ({len(series) - len(described)} further series omitted.)")
    return lines


def _describe_series_node(node: Any) -> str:
    if not isinstance(node, dict):
        return "unreadable series definition"
    parts = [f"{_math_label(node)} of {_series_subject(node)}"]
    filters = _describe_filters(node.get("properties"))
    if filters:
        parts.append(f"filtered to {filters}")
    return ", ".join(parts)


def _series_subject(node: dict[str, Any]) -> str:
    kind = node.get("kind")
    if kind == "ActionsNode":
        name = node.get("name")
        return f'action "{name}" (id {node.get("id")})' if name else f"action id {node.get('id')}"
    if kind == "DataWarehouseNode":
        return f'warehouse table "{node.get("table_name") or node.get("id")}"'
    event = node.get("event")
    if event is None:
        # An EventsNode with a null event matches every event, which is easy to
        # misread as "no filter configured yet".
        return "all events"
    return f'event "{event}"'


def _math_label(node: dict[str, Any]) -> str:
    math = node.get("math") or "total"
    if math == "hogql":
        return f"custom HogQL aggregation ({_clip(str(node.get('math_hogql') or ''), MAX_VALUE_CHARS)})"
    if math == "unique_group":
        return f"unique groups (group type index {node.get('math_group_type_index')})"
    label = _MATH_LABELS.get(math)
    if label:
        return label
    math_property = node.get("math_property")
    if math_property:
        return f'{math} of property "{math_property}"'
    return str(math)


def _describe_clauses(clauses: list[Any]) -> list[str]:
    lines: list[str] = []
    for index, clause in enumerate(clauses[:MAX_DESCRIBED_SERIES]):
        if not isinstance(clause, dict):
            continue
        described = f'- Clause {index}: metric "{clause.get("metricName")}"'
        filters = _describe_filters(clause.get("filters"))
        if filters:
            described += f", filtered to {filters}"
        lines.append(described)
    return lines


def _describe_query_scope(source: dict[str, Any], effective_date_range: MetricDateRange | None = None) -> list[str]:
    lines: list[str] = []

    global_filters = _describe_filters(source.get("properties"))
    if global_filters:
        lines.append(f"- Filters applied to every series: {global_filters}")

    breakdown = _describe_breakdown(source.get("breakdownFilter"))
    if breakdown:
        lines.append(f"- Breakdown: {breakdown}")

    if effective_date_range:
        lines.append(f"- The points below cover: {effective_date_range.start} to {effective_date_range.end}")
    else:
        date_range = source.get("dateRange")
        if isinstance(date_range, dict) and (date_range.get("date_from") or date_range.get("date_to")):
            lines.append(
                f"- Insight date range: {date_range.get('date_from') or 'default'} to "
                f"{date_range.get('date_to') or 'now'}"
            )

    interval = source.get("interval")
    if interval:
        lines.append(f"- Bucket interval: {interval}")

    if source.get("filterTestAccounts"):
        lines.append("- Internal and test accounts are excluded.")

    sampling_factor = source.get("samplingFactor")
    if sampling_factor is not None:
        lines.append(f"- Sampling factor: {sampling_factor}")

    return lines


def _describe_breakdown(breakdown_filter: Any) -> str | None:
    if not isinstance(breakdown_filter, dict):
        return None
    breakdowns = breakdown_filter.get("breakdowns")
    if isinstance(breakdowns, list) and breakdowns:
        described = [
            f"{item.get('type') or 'event'} {item.get('property')}" for item in breakdowns if isinstance(item, dict)
        ]
        return ", ".join(described) or None
    breakdown = breakdown_filter.get("breakdown")
    if breakdown:
        return f"{breakdown_filter.get('breakdown_type') or 'event'} {_format_value(breakdown)}"
    return None


def _describe_filters(properties: Any) -> str:
    leaves = _flatten_filters(properties, 0)
    described = [text for filter_ in leaves[:MAX_DESCRIBED_FILTERS] if (text := _describe_filter(filter_))]
    # Say what was dropped — an unannounced cut reads as "those are all the filters",
    # which is the same misreading of scope this block exists to prevent.
    if len(leaves) > MAX_DESCRIBED_FILTERS:
        described.append(f"and {len(leaves) - MAX_DESCRIBED_FILTERS} more filters not shown here")
    return "; ".join(described)


def _flatten_filters(properties: Any, depth: int) -> list[dict[str, Any]]:
    """Flatten property groups (AND/OR nestings) into a flat list of leaf filters.

    The nesting operators are dropped: for grounding the agent in what the metric
    covers, which properties are involved matters more than their boolean shape.
    """
    if depth > MAX_FILTER_DEPTH or properties is None:
        return []
    if isinstance(properties, list):
        return [leaf for item in properties for leaf in _flatten_filters(item, depth + 1)]
    if isinstance(properties, dict):
        values = properties.get("values")
        if isinstance(values, list):
            return [leaf for item in values for leaf in _flatten_filters(item, depth + 1)]
        return [properties] if properties.get("key") is not None or properties.get("type") == "cohort" else []
    return []


def _describe_filter(filter_: dict[str, Any]) -> str | None:
    filter_type = filter_.get("type") or "event"
    if filter_type == "cohort":
        return f"person is in cohort {_format_value(filter_.get('value'))}"
    key = filter_.get("key")
    if key is None:
        return None
    scope = _FILTER_SCOPE_LABELS.get(filter_type, f"{filter_type} property")
    if filter_type == "hogql":
        return f"{scope} {_clip(str(key), MAX_VALUE_CHARS)}"
    operator = filter_.get("operator") or "exact"
    operator_label = _OPERATOR_LABELS.get(operator, operator)
    if operator in _VALUELESS_OPERATORS:
        return f"{scope} {key} {operator_label}"
    return f"{scope} {key} {operator_label} {_format_value(filter_.get('value'))}"


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return _clip(value, MAX_VALUE_CHARS)
    return _clip(json.dumps(value, default=str), MAX_VALUE_CHARS)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
