import re

from posthog.schema import (
    AggregationAxisFormat,
    AssistantTrendsActionsNode,
    AssistantTrendsEventsNode,
    AssistantTrendsGroupNode,
    AssistantTrendsQuery,
    GroupMathType,
    PropertyMathType,
)

from posthog.hogql.errors import ExposedHogQLError

from posthog.hogql_queries.utils.formula_ast import FormulaAST

TrendsSeries = AssistantTrendsEventsNode | AssistantTrendsActionsNode | AssistantTrendsGroupNode

SECONDS_VALUED_MATH_PROPERTIES = frozenset({"$session_duration"})
"""Math properties the query engine returns in seconds. The taxonomy carries no unit, so this list is what we know."""

NON_DURATION_MATH_PROPERTIES = frozenset(
    {"$pageview_count", "$screen_count", "$autocapture_count", "$num_uniq_urls", "$is_bounce"}
)
"""Session math properties that hold a count or a boolean, so they are never a length of time."""

DURATION_AXIS_FORMATS = frozenset(
    {AggregationAxisFormat.DURATION, AggregationAxisFormat.DURATION_MS, AggregationAxisFormat.DURATION_NS}
)

MATH_COMPANION_FIELDS: tuple[tuple[frozenset[str], str, str], ...] = (
    (frozenset(PropertyMathType), "math_property", "aggregating a property"),
    (frozenset({"hogql"}), "math_hogql", "evaluating an expression"),
    (frozenset(GroupMathType), "math_group_type_index", "counting groups"),
)

NON_SECOND_TIME_UNIT = re.compile(r"\b(ms|hr|min|hour|day|milli|nano)", re.IGNORECASE)


def _series_label(index: int) -> str:
    return chr(ord("A") + index)


def _check_math_companion_field(series: TrendsSeries, label: str) -> str | None:
    """A math type without its companion field falls back to counting events, which reports a wrong number."""
    for math_types, field, intent in MATH_COMPANION_FIELDS:
        if series.math in math_types and getattr(series, field) is None:
            return (
                f"Series {label} uses the `{series.math}` math type, but `{field}` is unset. "
                f"The query counts events instead of {intent}. Set `{field}`, or use another math type."
            )
    return None


def _never_produces_a_duration(series: TrendsSeries) -> bool:
    """True when we know the series value is a count or a flag rather than a length of time."""
    if series.math_property is None:
        return series.math != "hogql"
    return series.math_property in NON_DURATION_MATH_PROPERTIES


def _check_axis_format(query: AssistantTrendsQuery) -> list[str]:
    trends_filter = query.trendsFilter
    if trends_filter is None:
        return []

    issues: list[str] = []
    axis_format = trends_filter.aggregationAxisFormat
    postfix = trends_filter.aggregationAxisPostfix or ""
    seconds_series = [
        _series_label(index)
        for index, series in enumerate(query.series)
        if series.math_property in SECONDS_VALUED_MATH_PROPERTIES
    ]

    if seconds_series:
        labels = ", ".join(seconds_series)
        if axis_format in DURATION_AXIS_FORMATS and axis_format != AggregationAxisFormat.DURATION:
            issues.append(
                f"Series {labels} aggregates a property measured in seconds, but the value axis uses "
                f"`{axis_format}`. That renders the value in the wrong unit. "
                f"Use the `duration` format, which reads the value as seconds."
            )
        if NON_SECOND_TIME_UNIT.search(postfix):
            issues.append(
                f"Series {labels} aggregates a property measured in seconds, but the axis postfix `{postfix}` "
                f"labels it with another time unit. That reports a wrong number. "
                f"Drop the postfix and use the `duration` format instead."
            )

    if (
        axis_format in DURATION_AXIS_FORMATS
        and not trends_filter.formulaNodes
        and query.series
        and all(_never_produces_a_duration(series) for series in query.series)
    ):
        issues.append(
            f"No series produces a length of time, but the value axis uses `{axis_format}`, which renders the "
            f"value as a duration. Use the `numeric` format, or aggregate a property measured in seconds."
        )

    return issues


def _check_formulas(query: AssistantTrendsQuery) -> list[str]:
    formula_nodes = query.trendsFilter.formulaNodes if query.trendsFilter else None
    if not formula_nodes:
        return []

    issues: list[str] = []
    for node in formula_nodes:
        try:
            # The engine evaluates a formula over the series values, so run it over placeholder values to
            # find the formulas it rejects: an undefined series, a function call, a comparison.
            FormulaAST([[0.0]] * len(query.series)).call(node.formula or "")
        except ExposedHogQLError as err:
            issues.append(f"The formula `{node.formula}` fails to run. {err}")
        except (SyntaxError, ValueError):
            issues.append(f"The formula `{node.formula}` is not a valid arithmetic expression between series.")
    return issues


def find_trends_quality_issues(query: AssistantTrendsQuery) -> list[str]:
    """
    Find generated trends queries that are valid against the schema, but still answer the question with a wrong
    number: a math type that silently degrades into an event count, a value the axis renders in the wrong unit,
    or a formula the query engine rejects.
    """
    issues: list[str] = []

    if not query.series:
        issues.append("The query defines no series, so it returns no data. Add at least one event or action series.")

    for index, series in enumerate(query.series):
        issue = _check_math_companion_field(series, _series_label(index))
        if issue:
            issues.append(issue)

    issues.extend(_check_axis_format(query))
    issues.extend(_check_formulas(query))

    return issues
