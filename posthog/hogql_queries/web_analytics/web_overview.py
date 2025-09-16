import math
from typing import Optional, Union

import structlog

from posthog.schema import (
    CachedWebOverviewQueryResponse,
    HogQLQueryModifiers,
    WebOverviewQuery,
    WebOverviewQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import revenue_sum_expression_for_events
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.hogql_queries.web_analytics.web_overview_pre_aggregated import WebOverviewPreAggregatedQueryBuilder
from posthog.models.filters.mixins.utils import cached_property

logger = structlog.get_logger(__name__)


class WebOverviewQueryRunner(WebAnalyticsQueryRunner[WebOverviewQueryResponse]):
    query: WebOverviewQuery
    cached_response: CachedWebOverviewQueryResponse
    preaggregated_query_builder: WebOverviewPreAggregatedQueryBuilder

    def __init__(self, *args, use_v2_tables: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        # Determine table version from team property, fallback to parameter for compatibility
        team_version = getattr(self.team, "web_analytics_pre_aggregated_tables_version", "v2")
        self.use_v2_tables = team_version == "v2" if team_version else use_v2_tables
        self.preaggregated_query_builder = WebOverviewPreAggregatedQueryBuilder(self)

    def to_query(self) -> ast.SelectQuery:
        return self.outer_select

    def get_pre_aggregated_response(self):
        should_use_preaggregated = (
            self.modifiers
            and self.modifiers.useWebAnalyticsPreAggregatedTables
            and self.preaggregated_query_builder.can_use_preaggregated_tables()
        )

        if not should_use_preaggregated:
            return None

        try:
            # Pre-aggregated tables store data in UTC **buckets**, so we need to disable timezone conversion
            # to prevent HogQL from automatically converting DateTime fields to team timezone.
            # We don't plot or show the actual bucket dates anywhere, so since this is just filtering,
            # we can rely on the bucket aggregation to get the correct results for the time window.
            pre_agg_modifiers = self.modifiers.model_copy() if self.modifiers else HogQLQueryModifiers()
            pre_agg_modifiers.convertToProjectTimezone = False

            response = execute_hogql_query(
                query_type="web_overview_preaggregated_query",
                query=self.preaggregated_query_builder.get_query(),
                team=self.team,
                timings=self.timings,
                modifiers=pre_agg_modifiers,
                limit_context=self.limit_context,
            )

            # We could have a empty result in normal conditions but also when we're recreating the tables.
            # While we're testing, if it is a empty result, let's  fallback on using the
            # regular queries to be extra careful.
            assert response.results

            return response
        except Exception as e:
            logger.exception("Error getting pre-aggregated web_overview", error=e)
            return None

    def _calculate(self) -> WebOverviewQueryResponse:
        pre_aggregated_response = self.get_pre_aggregated_response()

        response = (
            execute_hogql_query(
                query_type="web_overview_query",
                query=self.to_query(),
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
            if not pre_aggregated_response
            else pre_aggregated_response
        )

        assert response.results

        row = response.results[0]
        include_previous = bool(self.query.compareFilter and self.query.compareFilter.compare)

        def get_prev_val(idx, use_unsample=True):
            if not include_previous:
                return None
            return self._unsample(row[idx]) if use_unsample else row[idx]

        if self.query.conversionGoal:
            results = [
                to_data("visitors", "unit", self._unsample(row[0]), get_prev_val(1)),
                to_data("total conversions", "unit", self._unsample(row[2]), get_prev_val(3)),
                to_data("unique conversions", "unit", self._unsample(row[4]), get_prev_val(5)),
                to_data("conversion rate", "percentage", row[6], get_prev_val(7, False)),
            ]
        else:
            results = [
                to_data("visitors", "unit", self._unsample(row[0]), get_prev_val(1)),
                to_data("views", "unit", self._unsample(row[2]), get_prev_val(3)),
                to_data("sessions", "unit", self._unsample(row[4]), get_prev_val(5)),
                to_data("session duration", "duration_s", row[6], get_prev_val(7, False)),
                to_data("bounce rate", "percentage", row[8], get_prev_val(9, False), is_increase_bad=True),
            ]

        if self.query.includeRevenue:
            if self.query.conversionGoal:
                results.append(to_data("conversion revenue", "currency", row[8], get_prev_val(9, False)))
            else:
                results.append(to_data("revenue", "currency", row[10], get_prev_val(11, False)))

        return WebOverviewQueryResponse(
            results=results,
            samplingRate=self._sample_rate,
            modifiers=self.modifiers,
            dateFrom=self.query_date_range.date_from_str,
            dateTo=self.query_date_range.date_to_str,
            usedPreAggregatedTables=response == pre_aggregated_response,
        )

    def all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    @cached_property
    def pageview_count_expression(self) -> ast.Expr:
        return ast.Call(
            name="countIf",
            args=[
                ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["event"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value="$pageview"),
                        ),
                        ast.CompareOperation(
                            left=ast.Field(chain=["event"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value="$screen"),
                        ),
                    ]
                )
            ],
        )

    @cached_property
    def inner_select(self) -> ast.SelectQuery:
        parsed_select = parse_select(
            """
SELECT
    any(events.person_id) as session_person_id,
    session.session_id as session_id,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and(
    {events_session_id} IS NOT NULL,
    {event_type_expr},
    {inside_timestamp_period},
    {all_properties},
)
GROUP BY session_id
HAVING {inside_start_timestamp_period}
        """,
            placeholders={
                "all_properties": self.all_properties(),
                "event_type_expr": self.event_type_expr,
                "inside_timestamp_period": self._periods_expression("timestamp"),
                "inside_start_timestamp_period": self._periods_expression("start_timestamp"),
                "events_session_id": self.events_session_property,
            },
        )
        assert isinstance(parsed_select, ast.SelectQuery)

        if self.conversion_count_expr and self.conversion_person_id_expr:
            parsed_select.select.append(ast.Alias(alias="conversion_count", expr=self.conversion_count_expr))
            parsed_select.select.append(ast.Alias(alias="conversion_person_id", expr=self.conversion_person_id_expr))
            if self.query.includeRevenue:
                parsed_select.select.append(
                    ast.Alias(alias="session_conversion_revenue", expr=self.conversion_revenue_expr)
                )

        else:
            parsed_select.select.append(
                ast.Alias(
                    alias="session_duration",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$session_duration"])]),
                )
            )
            parsed_select.select.append(ast.Alias(alias="filtered_pageview_count", expr=self.pageview_count_expression))
            parsed_select.select.append(
                ast.Alias(
                    alias="is_bounce", expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$is_bounce"])])
                )
            )
            if self.query.includeRevenue:
                parsed_select.select.append(
                    ast.Alias(
                        alias="session_revenue",
                        expr=revenue_sum_expression_for_events(self.team),
                    )
                )

        return parsed_select

    @cached_property
    def outer_select(self) -> ast.SelectQuery:
        has_comparison = bool(self.query_compare_to_date_range)

        def current_period_aggregate(
            function_name: str,
            column_name: str,
            alias: str,
            params: Optional[list[ast.Expr]] = None,
        ):
            if not has_comparison:
                return ast.Alias(
                    alias=alias, expr=ast.Call(name=function_name, params=params, args=[ast.Field(chain=[column_name])])
                )

            return self.period_aggregate(
                function_name,
                column_name,
                self.query_date_range.date_from_as_hogql(),
                self.query_date_range.date_to_as_hogql(),
                alias=alias,
                params=params,
            )

        def previous_period_aggregate(
            function_name: str,
            column_name: str,
            alias: str,
            params: Optional[list[ast.Expr]] = None,
        ):
            if not has_comparison:
                return ast.Alias(alias=alias, expr=ast.Constant(value=None))

            return self.period_aggregate(
                function_name,
                column_name,
                self.query_compare_to_date_range.date_from_as_hogql(),
                self.query_compare_to_date_range.date_to_as_hogql(),
                alias=alias,
                params=params,
            )

        def metric_pair(
            function_name: str,
            column_name: str,
            current_alias: str,
            previous_alias: Optional[str] = None,
            params: Optional[list[ast.Expr]] = None,
        ) -> list[ast.Expr]:
            # This could also be done using tuples like the stats_table but I will keep the protocol as close as possible: https://github.com/PostHog/posthog/blob/26588f3689aa505fbf857afcae4e8bd18cf75606/posthog/hogql_queries/web_analytics/stats_table.py#L390-L399
            previous_alias = previous_alias or f"previous_{current_alias}"
            return [
                current_period_aggregate(function_name, column_name, current_alias, params),
                previous_period_aggregate(function_name, column_name, previous_alias, params),
            ]

        select: list[ast.Expr] = []

        if self.query.conversionGoal:
            # Add standard conversion goal metrics
            select.extend(metric_pair("uniq", "session_person_id", "unique_users"))
            select.extend(metric_pair("sum", "conversion_count", "total_conversion_count"))
            select.extend(metric_pair("uniq", "conversion_person_id", "unique_conversions"))

            conversion_rate = ast.Alias(
                alias="conversion_rate",
                expr=ast.Call(
                    name="divide",
                    args=[
                        ast.Field(chain=["unique_conversions"]),
                        ast.Field(chain=["unique_users"]),
                    ],
                ),
            )

            previous_conversion_rate = ast.Alias(
                alias="previous_conversion_rate",
                expr=(
                    ast.Constant(value=None)
                    if not has_comparison
                    else ast.Call(
                        name="divide",
                        args=[
                            ast.Field(chain=["previous_unique_conversions"]),
                            ast.Field(chain=["previous_unique_users"]),
                        ],
                    )
                ),
            )

            select.extend([conversion_rate, previous_conversion_rate])

            if self.query.includeRevenue:
                select.extend(metric_pair("sum", "session_conversion_revenue", "conversion_revenue"))

        else:
            select.extend(metric_pair("uniq", "session_person_id", "unique_users"))
            select.extend(metric_pair("sum", "filtered_pageview_count", "total_filtered_pageview_count"))
            select.extend(metric_pair("uniq", "session_id", "unique_sessions"))
            select.extend(metric_pair("avg", "session_duration", "avg_duration_s"))
            select.extend(metric_pair("avg", "is_bounce", "bounce_rate"))

            if self.query.includeRevenue:
                select.extend(metric_pair("sum", "session_revenue", "revenue"))

        return ast.SelectQuery(select=select, select_from=ast.JoinExpr(table=self.inner_select))


def to_data(
    key: str,
    kind: str,
    value: Optional[Union[float, list[float]]],
    previous: Optional[Union[float, list[float]]],
    is_increase_bad: Optional[bool] = None,
) -> dict:
    if isinstance(value, list):
        value = value[0]
    if isinstance(previous, list):
        previous = previous[0]
    if value is not None and math.isnan(value):
        value = None
    if previous is not None and math.isnan(previous):
        previous = None
    if kind == "percentage":
        if value is not None:
            value = value * 100
        if previous is not None:
            previous = previous * 100
    if kind == "duration_ms":
        kind = "duration_s"
        if value is not None:
            value = value / 1000
        if previous is not None:
            previous = previous / 1000

    change_from_previous_pct = None
    if value is not None and previous is not None and previous != 0:
        try:
            change_from_previous_pct = round(100 * (value - previous) / previous)
        except ValueError:
            pass

    return {
        "key": key,
        "kind": kind,
        "isIncreaseBad": is_increase_bad,
        "value": value,
        "previous": previous,
        "changeFromPreviousPct": change_from_previous_pct,
    }
