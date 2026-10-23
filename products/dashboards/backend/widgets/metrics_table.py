from __future__ import annotations

import math
from typing import Any

from django.utils import timezone

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import relative_date_parse

from products.dashboards.backend.constants import METRICS_TABLE_SPARKLINE_POINTS
from products.dashboards.backend.widget_specs.configs import METRICS_TABLE_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.metrics.backend.facade.api import run_metric_query
from products.metrics.backend.facade.contracts import (
    MetricFilter,
    MetricGroupBy,
    MetricQueryClause,
    MetricQueryRequest,
    MetricSeries,
)
from products.metrics.backend.facade.enums import FilterOp, MetricAggregation, MetricRangeFunction

DEFAULT_METRICS_TABLE_DATE_FROM = "-1h"

# A counter column sums the per-series change, so each row is the total for its label value.
_COUNTER_FUNCTIONS = {"rate": MetricRangeFunction.RATE, "increase": MetricRangeFunction.INCREASE}


def _clause(index: int, column: dict[str, Any], group_by: str) -> MetricQueryClause:
    aggregation = column["aggregation"]
    range_function = _COUNTER_FUNCTIONS.get(aggregation)
    return MetricQueryClause(
        name=f"c{index}",
        metric_name=column["metricName"],
        aggregation=MetricAggregation.SUM if range_function else MetricAggregation(aggregation),
        range_function=range_function,
        quantile=column.get("quantile"),
        filters=tuple(
            MetricFilter(key=item["key"], op=FilterOp(item["op"]), value=item["value"])
            for item in column.get("filters", [])
        ),
        group_by=(MetricGroupBy(key=group_by),),
    )


def _mean(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    return sum(finite) / len(finite) if finite else None


def _sparkline(series: MetricSeries) -> list[float | None]:
    values = [point.value for point in series.points]
    if len(values) <= METRICS_TABLE_SPARKLINE_POINTS:
        return values
    size = math.ceil(len(values) / METRICS_TABLE_SPARKLINE_POINTS)
    return [
        _mean([value for value in values[start : start + size] if value is not None])
        for start in range(0, len(values), size)
    ]


def _sort_key(row: dict[str, Any], column: int, descending: bool) -> tuple[bool, float, str]:
    value = row["values"][column]
    # Rows without a value go last in both directions.
    if value is None:
        return (True, 0.0, row["key"])
    return (False, -value if descending else value, row["key"])


def run_metrics_table_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(METRICS_TABLE_WIDGET_TYPE, config)
    group_by = typed_config.get("groupBy")
    columns: list[dict[str, Any]] = typed_config["columns"]
    if not group_by or not columns:
        return {"needsConfiguration": True, "groupBy": group_by, "columns": [], "rows": [], "totalCount": 0}

    date_from = (typed_config.get("dateRange") or {}).get("date_from") or DEFAULT_METRICS_TABLE_DATE_FROM
    request = MetricQueryRequest(
        clauses=tuple(_clause(index, column, group_by) for index, column in enumerate(columns)),
        date_from=relative_date_parse(date_from, team.timezone_info),
        date_to=timezone.now(),
    )
    with tags_context(product=Product.METRICS, feature=Feature.QUERY, team_id=team.pk):
        series = run_metric_query(team=team, request=request)

    rows_by_key: dict[str, dict[str, Any]] = {}
    units: list[str | None] = [None] * len(columns)
    for item in series:
        key = item.labels.get(group_by)
        if key is None or item.clause is None:
            continue
        index = int(item.clause.removeprefix("c"))
        units[index] = units[index] or item.unit
        row = rows_by_key.setdefault(
            key, {"key": key, "values": [None] * len(columns), "sparklines": [[] for _ in columns]}
        )
        row["values"][index] = _mean([point.value for point in item.points if point.value is not None])
        row["sparklines"][index] = _sparkline(item)

    ordered = sorted(
        rows_by_key.values(),
        key=lambda row: _sort_key(row, typed_config["orderByColumn"], typed_config["orderDirection"] == "DESC"),
    )
    limit = typed_config["limit"]
    return {
        "needsConfiguration": False,
        "groupBy": group_by,
        "columns": [
            {"label": column["label"], "aggregation": column["aggregation"], "unit": unit}
            for column, unit in zip(columns, units)
        ],
        "rows": ordered[:limit],
        "totalCount": len(ordered),
        "hasMore": len(ordered) > limit,
    }
