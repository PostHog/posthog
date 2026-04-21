import math
from typing import Required, TypedDict, Union

import structlog

from posthog.schema import (
    CachedWebNotableChangesQueryResponse,
    HogQLQueryModifiers,
    WebNotableChangeItem,
    WebNotableChangesQuery,
    WebNotableChangesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import wrap_with_null_if_empty
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.web_analytics.pre_aggregated.properties import STATS_TABLE_SUPPORTED_FILTERS
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner

logger = structlog.get_logger(__name__)

MIN_TRAFFIC_THRESHOLD = 10
DEFAULT_LIMIT = 8


class DimensionConfig(TypedDict, total=False):
    label: Required[str]
    field: str | None
    is_path: bool
    is_channel: bool
    raw_field: list[str | int] | None


DIMENSIONS: list[DimensionConfig] = [
    {"label": "Page", "field": "pathname", "is_path": True, "raw_field": ["events", "properties", "$pathname"]},
    {"label": "Entry page", "field": "entry_pathname", "is_path": True, "raw_field": ["session", "$entry_pathname"]},
    {"label": "Referrer", "field": "referring_domain", "raw_field": ["session", "$entry_referring_domain"]},
    {"label": "Device", "field": "device_type", "raw_field": ["events", "properties", "$device_type"]},
    {"label": "Browser", "field": "browser", "raw_field": ["events", "properties", "$browser"]},
    {"label": "Country", "field": "country_code", "raw_field": ["events", "properties", "$geoip_country_code"]},
    {"label": "Channel", "field": None, "is_channel": True, "raw_field": None},
    {"label": "UTM source", "field": "utm_source", "raw_field": ["session", "$entry_utm_source"]},
]


class WebNotableChangesQueryRunner(WebAnalyticsQueryRunner[WebNotableChangesQueryResponse]):
    query: WebNotableChangesQuery
    cached_response: CachedWebNotableChangesQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.preaggregated_query_builder = _NotableChangesPreAggregatedQueryBuilder(self)

    def to_query(self) -> Union[ast.SelectQuery, ast.SelectSetQuery]:
        return self._raw_events_query()

    def _calculate(self) -> WebNotableChangesQueryResponse:
        pre_agg_response = self._get_pre_aggregated_response()
        if pre_agg_response is not None:
            response = pre_agg_response
            used_preagg = True
        else:
            response = execute_hogql_query(
                query_type="web_notable_changes_query",
                query=self.to_query(),
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
            used_preagg = False

        if not response.results:
            return WebNotableChangesQueryResponse(
                results=[],
                samplingRate=self._sample_rate,
                modifiers=self.modifiers,
                usedPreAggregatedTables=used_preagg,
            )

        scored_items = self._score_results(response.results)
        limit = self.query.limit or DEFAULT_LIMIT
        top_items = scored_items[:limit]

        return WebNotableChangesQueryResponse(
            results=top_items,
            samplingRate=self._sample_rate,
            modifiers=self.modifiers,
            usedPreAggregatedTables=used_preagg,
        )

    def _get_pre_aggregated_response(self):
        should_use_preaggregated = (
            self.modifiers
            and self.modifiers.useWebAnalyticsPreAggregatedTables
            and self.preaggregated_query_builder.can_use_preaggregated_tables()
        )

        if not should_use_preaggregated:
            return None

        try:
            pre_agg_modifiers = self.modifiers.model_copy() if self.modifiers else HogQLQueryModifiers()
            pre_agg_modifiers.convertToProjectTimezone = False

            response = execute_hogql_query(
                query_type="web_notable_changes_query",
                query=self.preaggregated_query_builder.get_query(),
                team=self.team,
                timings=self.timings,
                modifiers=pre_agg_modifiers,
                limit_context=self.limit_context,
            )

            if not response.results:
                return None
            return response
        except Exception as e:
            logger.exception("Error getting pre-aggregated notable changes", error=e)
            return None

    def _raw_events_query(self) -> Union[ast.SelectQuery, ast.SelectSetQuery]:
        all_properties = property_to_expr(
            [*self.query.properties, *self._test_account_filters],
            team=self.team,
        )
        periods = self._periods_expression("timestamp")
        current_period = self._current_period_expression("start_timestamp")
        previous_period = self._previous_period_expression("start_timestamp")

        subqueries: list[ast.SelectQuery] = []
        for dim in DIMENSIONS:
            if dim.get("is_channel"):
                raw_expr: ast.Expr = ast.Field(chain=["session", "$channel_type"])
            elif dim.get("raw_field"):
                raw_field = dim["raw_field"]
                assert raw_field is not None
                raw_expr = ast.Field(chain=raw_field)
            else:
                continue

            if dim.get("is_path") and self.query.doPathCleaning:
                raw_expr = self._apply_path_cleaning(raw_expr)

            dimension_expr = wrap_with_null_if_empty(raw_expr)

            inner_query = ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias="person_id", expr=ast.Call(name="any", args=[ast.Field(chain=["events", "person_id"])])
                    ),
                    ast.Alias(alias="dimension_value", expr=dimension_expr),
                    ast.Alias(alias="session_id", expr=ast.Field(chain=["session", "session_id"])),
                    ast.Alias(
                        alias="start_timestamp",
                        expr=ast.Call(name="min", args=[ast.Field(chain=["session", "$start_timestamp"])]),
                    ),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=ast.Call(
                    name="and",
                    args=[
                        self.event_type_expr,
                        periods,
                        all_properties,
                    ],
                ),
                group_by=[
                    ast.Field(chain=["session", "session_id"]),
                    dimension_expr,
                ],
            )

            outer_query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="dimension_type", expr=ast.Constant(value=dim["label"])),
                    ast.Alias(alias="dimension_value", expr=ast.Field(chain=["dimension_value"])),
                    ast.Alias(
                        alias="current_visitors",
                        expr=ast.Call(name="uniqIf", args=[ast.Field(chain=["person_id"]), current_period]),
                    ),
                    ast.Alias(
                        alias="previous_visitors",
                        expr=ast.Call(name="uniqIf", args=[ast.Field(chain=["person_id"]), previous_period]),
                    ),
                ],
                select_from=ast.JoinExpr(table=inner_query),
                group_by=[ast.Field(chain=["dimension_value"])],
                having=ast.And(
                    exprs=[
                        ast.Call(
                            name="isNotNull",
                            args=[ast.Field(chain=["dimension_value"])],
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.NotEq,
                            left=ast.Field(chain=["dimension_value"]),
                            right=ast.Constant(value=""),
                        ),
                    ]
                ),
            )

            subqueries.append(outer_query)

        return ast.SelectSetQuery.create_from_queries(subqueries, "UNION ALL")

    def _score_results(self, results: list) -> list[WebNotableChangeItem]:
        items: list[WebNotableChangeItem] = []
        for row in results:
            dimension_type = row[0]
            dimension_value = row[1]
            current = row[2] or 0
            previous = row[3] or 0

            if current + previous < MIN_TRAFFIC_THRESHOLD:
                continue

            if previous == 0:
                percent_change = min(10.0, float(current))
            else:
                percent_change = (current - previous) / previous

            baseline = max(current, previous)
            impact_score = abs(percent_change) * math.sqrt(baseline)

            items.append(
                WebNotableChangeItem(
                    dimension_type=dimension_type,
                    dimension_value=str(dimension_value),
                    metric="visitors",
                    current_value=int(current),
                    previous_value=int(previous),
                    percent_change=round(percent_change, 4),
                    impact_score=round(impact_score, 2),
                )
            )

        items.sort(key=lambda x: x.impact_score, reverse=True)
        return items


class _NotableChangesPreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    def __init__(self, runner: WebNotableChangesQueryRunner) -> None:
        super().__init__(runner=runner, supported_props_filters=STATS_TABLE_SUPPORTED_FILTERS)

    def get_query(self) -> Union[ast.SelectQuery, ast.SelectSetQuery]:
        previous_period_filter, current_period_filter = self.get_date_ranges()
        table_name = self.stats_table

        subqueries: list[ast.SelectQuery] = []
        for dim in DIMENSIONS:
            subquery = self._build_dimension_subquery(dim, table_name, current_period_filter, previous_period_filter)
            subqueries.append(subquery)

        return ast.SelectSetQuery.create_from_queries(subqueries, "UNION ALL")

    def _build_dimension_subquery(
        self,
        dim: DimensionConfig,
        table_name: str,
        current_period_filter: ast.Expr,
        previous_period_filter: ast.Expr,
    ) -> ast.SelectQuery:
        label = dim["label"]

        if dim.get("is_channel"):
            dimension_expr = self._get_channel_type_expr()
        elif dim.get("is_path") and self.runner.query.doPathCleaning:
            field = dim["field"]
            assert field is not None
            dimension_expr = self.runner._apply_path_cleaning(ast.Field(chain=[field]))
        else:
            field = dim["field"]
            assert field is not None
            dimension_expr = ast.Field(chain=[field])

        dimension_expr_wrapped = wrap_with_null_if_empty(dimension_expr)

        current_visitors = ast.Call(
            name="uniqMergeIf",
            args=[ast.Field(chain=["persons_uniq_state"]), current_period_filter],
        )
        previous_visitors = ast.Call(
            name="uniqMergeIf",
            args=[ast.Field(chain=["persons_uniq_state"]), previous_period_filter],
        )

        filters = self._get_filters(table_name=table_name)

        select_columns: list[ast.Expr] = [
            ast.Alias(alias="dimension_type", expr=ast.Constant(value=label)),
            ast.Alias(alias="dimension_value", expr=dimension_expr_wrapped),
            ast.Alias(alias="current_visitors", expr=current_visitors),
            ast.Alias(alias="previous_visitors", expr=previous_visitors),
        ]

        having_expr = ast.Call(
            name="isNotNull",
            args=[ast.Field(chain=["dimension_value"])],
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
            where=filters,
            group_by=[dimension_expr_wrapped],
            having=having_expr,
        )
