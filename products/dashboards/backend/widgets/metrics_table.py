from __future__ import annotations

import math
from typing import Any

from django.utils import timezone

from rest_framework import exceptions

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import relative_date_parse

from products.dashboards.backend.constants import METRICS_TABLE_SPARKLINE_POINTS
from products.dashboards.backend.feature_flags import widget_flag_enabled
from products.dashboards.backend.widget_specs.configs import METRICS_TABLE_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.metrics.backend.facade.api import (
    metric_query_concurrency_slots,
    pick_metric_query_interval,
    run_metric_query,
)
from products.metrics.backend.facade.contracts import (
    METRICS_FEATURE_FLAG,
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


def _order_rows(rows: list[dict[str, Any]], column: int, descending: bool) -> list[dict[str, Any]]:
    # Python sorts are stable, so ties keep the key order. Rows without a value go last in both directions.
    by_key = sorted(rows, key=lambda row: row["key"])
    with_value = sorted(
        (row for row in by_key if row["values"][column] is not None),
        key=lambda row: row["values"][column],
        reverse=descending,
    )
    return with_value + [row for row in by_key if row["values"][column] is None]


def run_metrics_table_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    # The creation flag only blocks new tiles. Metrics is in private alpha, so every run checks the flag too.
    if not widget_flag_enabled(METRICS_FEATURE_FLAG, team=team, user=user):
        raise exceptions.PermissionDenied("Metrics are not enabled for this project.")
    typed_config = validate_widget_config(METRICS_TABLE_WIDGET_TYPE, config)
    group_by = typed_config.get("groupBy")
    columns: list[dict[str, Any]] = typed_config["columns"]
    if not group_by or not columns:
        return {"needsConfiguration": True, "groupBy": group_by, "columns": [], "rows": [], "totalCount": 0}

    date_from_value = (typed_config.get("dateRange") or {}).get("date_from") or DEFAULT_METRICS_TABLE_DATE_FROM
    date_from = relative_date_parse(date_from_value, team.timezone_info)
    date_to = timezone.now()
    request = MetricQueryRequest(
        clauses=tuple(_clause(index, column, group_by) for index, column in enumerate(columns)),
        date_from=date_from,
        date_to=date_to,
        interval=pick_metric_query_interval(
            date_from=date_from, date_to=date_to, max_buckets=METRICS_TABLE_SPARKLINE_POINTS
        ),
    )
    with (
        tags_context(product=Product.METRICS, feature=Feature.QUERY, team_id=team.pk),
        metric_query_concurrency_slots(team),
    ):
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

    ordered = _order_rows(
        list(rows_by_key.values()), typed_config["orderByColumn"], typed_config["orderDirection"] == "DESC"
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
