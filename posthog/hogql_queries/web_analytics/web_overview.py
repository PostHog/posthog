from typing import Optional, Union
import math

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    CachedWebOverviewQueryResponse,
    WebOverviewQueryResponse,
    WebOverviewQuery,
)
from posthog.hogql.database.schema.exchange_rate import revenue_sum_expression_for_events


class WebOverviewQueryRunner(WebAnalyticsQueryRunner):
    query: WebOverviewQuery
    response: WebOverviewQueryResponse
    cached_response: CachedWebOverviewQueryResponse

    def to_query(self) -> ast.SelectQuery:
        return self.outer_select

    def calculate(self):
        response = execute_hogql_query(
            query_type="overview_stats_pages_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        assert response.results

        row = response.results[0]
        include_previous = bool(self.query.compareFilter and self.query.compareFilter.compare)

        def get_prev_val(idx, use_unsample=True):
            if not include_previous:
                return None
            return self._unsample(row[idx]) if use_unsample else row[idx]

        def create_base_metrics():
            """Create metrics based on whether we're showing conversion goals or standard metrics"""
            if self.query.conversionGoal:
                return [
                    to_data("visitors", "unit", self._unsample(row[0]), get_prev_val(1)),
                    to_data("total conversions", "unit", self._unsample(row[2]), get_prev_val(3)),
                    to_data("unique conversions", "unit", self._unsample(row[4]), get_prev_val(5)),
                    to_data("conversion rate", "percentage", row[6], get_prev_val(7, False)),
                ]
            else:
                return [
                    to_data("visitors", "unit", self._unsample(row[0]), get_prev_val(1)),
                    to_data("views", "unit", self._unsample(row[2]), get_prev_val(3)),
                    to_data("sessions", "unit", self._unsample(row[4]), get_prev_val(5)),
                    to_data("session duration", "duration_s", row[6], get_prev_val(7, False)),
                    to_data("bounce rate", "percentage", row[8], get_prev_val(9, False), is_increase_bad=True),
                ]

        def add_revenue_metrics(metrics):
            """Add revenue metrics if they should be included"""
            if not self.query.includeRevenue:
                return metrics

            if self.query.conversionGoal:
                metrics.append(to_data("conversion revenue", "currency", row[8], get_prev_val(9, False)))
            else:
                metrics.append(to_data("revenue", "currency", row[10], get_prev_val(11, False)))
            return metrics

        results = add_revenue_metrics(create_base_metrics())

        return WebOverviewQueryResponse(
            results=results,
            samplingRate=self._sample_rate,
            modifiers=self.modifiers,
            dateFrom=self.query_date_range.date_from_str,
            dateTo=self.query_date_range.date_to_str,
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
                        expr=revenue_sum_expression_for_events(self.team.revenue_config),
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

        def add_metric_pair(
            metrics_list: list[ast.Expr],
            function_name: str,
            column_name: str,
            current_alias: str,
            previous_alias: Optional[str] = None,
            params: Optional[list[ast.Expr]] = None,
        ) -> list[ast.Expr]:
            # This could also be done using tuples like the stats_table but I will keep the protocol as close as possible: https://github.com/PostHog/posthog/blob/26588f3689aa505fbf857afcae4e8bd18cf75606/posthog/hogql_queries/web_analytics/stats_table.py#L390-L399
            previous_alias = previous_alias or f"previous_{current_alias}"
            metrics_list.append(current_period_aggregate(function_name, column_name, current_alias, params))
            metrics_list.append(previous_period_aggregate(function_name, column_name, previous_alias, params))
            return metrics_list

        select: list[ast.Expr] = []

        if self.query.conversionGoal:
            # Add standard conversion goal metrics
            add_metric_pair(select, "uniq", "session_person_id", "unique_users")
            add_metric_pair(select, "sum", "conversion_count", "total_conversion_count")
            add_metric_pair(select, "uniq", "conversion_person_id", "unique_conversions")

            conversion_rate: ast.Expr = ast.Alias(
                alias="conversion_rate",
                expr=ast.Call(
                    name="divide",
                    args=[
                        ast.Field(chain=["unique_conversions"]) if has_comparison else select[4].expr,
                        ast.Field(chain=["unique_users"]) if has_comparison else ast.Field(chain=["unique_users"]),
                    ],
                ),
            )

            previous_conversion_rate: ast.Expr = ast.Alias(
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
                add_metric_pair(select, "sum", "session_conversion_revenue", "conversion_revenue")

        else:
            add_metric_pair(select, "uniq", "session_person_id", "unique_users")
            add_metric_pair(select, "sum", "filtered_pageview_count", "total_filtered_pageview_count")
            add_metric_pair(select, "uniq", "session_id", "unique_sessions")
            add_metric_pair(select, "avg", "session_duration", "avg_duration_s", previous_alias="prev_avg_duration_s")
            add_metric_pair(select, "avg", "is_bounce", "bounce_rate", previous_alias="prev_bounce_rate")

            if self.query.includeRevenue:
                add_metric_pair(select, "sum", "session_revenue", "revenue")

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
        except (ValueError, ZeroDivisionError):
            pass

    return {
        "key": key,
        "kind": kind,
        "isIncreaseBad": is_increase_bad,
        "value": value,
        "previous": previous,
        "changeFromPreviousPct": change_from_previous_pct,
    }
