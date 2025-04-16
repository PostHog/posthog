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

        # Only include previous period data if comparison is enabled
        include_previous = bool(self.query.compareFilter and self.query.compareFilter.compare)

        if self.query.conversionGoal:
            results = [
                to_data(
                    "visitors", "unit", self._unsample(row[0]), self._unsample(row[1]) if include_previous else None
                ),
                to_data(
                    "total conversions",
                    "unit",
                    self._unsample(row[2]),
                    self._unsample(row[3]) if include_previous else None,
                ),
                to_data(
                    "unique conversions",
                    "unit",
                    self._unsample(row[4]),
                    self._unsample(row[5]) if include_previous else None,
                ),
                to_data("conversion rate", "percentage", row[6], row[7] if include_previous else None),
            ]
            if self.query.includeRevenue:
                results.append(to_data("conversion revenue", "currency", row[8], row[9] if include_previous else None))
        else:
            results = [
                to_data(
                    "visitors", "unit", self._unsample(row[0]), self._unsample(row[1]) if include_previous else None
                ),
                to_data("views", "unit", self._unsample(row[2]), self._unsample(row[3]) if include_previous else None),
                to_data(
                    "sessions", "unit", self._unsample(row[4]), self._unsample(row[5]) if include_previous else None
                ),
                to_data("session duration", "duration_s", row[6], row[7] if include_previous else None),
                to_data(
                    "bounce rate", "percentage", row[8], row[9] if include_previous else None, is_increase_bad=True
                ),
            ]
            if self.query.includeRevenue:
                results.append(to_data("revenue", "currency", row[10], row[11] if include_previous else None))

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

        if self.query.conversionGoal:
            # For conversion goals, we need to handle the case where comparison is disabled
            unique_users = current_period_aggregate("uniq", "session_person_id", "unique_users")
            previous_unique_users = previous_period_aggregate("uniq", "session_person_id", "previous_unique_users")
            total_conversion_count = current_period_aggregate("sum", "conversion_count", "total_conversion_count")
            previous_total_conversion_count = previous_period_aggregate(
                "sum", "conversion_count", "previous_total_conversion_count"
            )
            unique_conversions = current_period_aggregate("uniq", "conversion_person_id", "unique_conversions")
            previous_unique_conversions = previous_period_aggregate(
                "uniq", "conversion_person_id", "previous_unique_conversions"
            )

            # Create appropriate conversion rate calculations
            conversion_rate = ast.Alias(
                alias="conversion_rate",
                expr=ast.Call(
                    name="divide",
                    args=[
                        ast.Field(chain=["unique_conversions"]) if has_comparison else unique_users.expr,
                        ast.Field(chain=["unique_users"]) if has_comparison else ast.Field(chain=["unique_users"]),
                    ],
                ),
            )

            previous_conversion_rate = ast.Alias(
                alias="previous_conversion_rate",
                expr=ast.Constant(value=None)
                if not has_comparison
                else ast.Call(
                    name="divide",
                    args=[
                        ast.Field(chain=["previous_unique_conversions"]),
                        ast.Field(chain=["previous_unique_users"]),
                    ],
                ),
            )

            select = [
                unique_users,
                previous_unique_users,
                total_conversion_count,
                previous_total_conversion_count,
                unique_conversions,
                previous_unique_conversions,
                conversion_rate,
                previous_conversion_rate,
            ]

            if self.query.includeRevenue:
                select.extend(
                    [
                        current_period_aggregate("sum", "session_conversion_revenue", "conversion_revenue"),
                        previous_period_aggregate("sum", "session_conversion_revenue", "previous_conversion_revenue"),
                    ]
                )
        else:
            select = [
                current_period_aggregate("uniq", "session_person_id", "unique_users"),
                previous_period_aggregate("uniq", "session_person_id", "previous_unique_users"),
                current_period_aggregate("sum", "filtered_pageview_count", "total_filtered_pageview_count"),
                previous_period_aggregate("sum", "filtered_pageview_count", "previous_filtered_pageview_count"),
                current_period_aggregate("uniq", "session_id", "unique_sessions"),
                previous_period_aggregate("uniq", "session_id", "previous_unique_sessions"),
                current_period_aggregate("avg", "session_duration", "avg_duration_s"),
                previous_period_aggregate("avg", "session_duration", "prev_avg_duration_s"),
                current_period_aggregate("avg", "is_bounce", "bounce_rate"),
                previous_period_aggregate("avg", "is_bounce", "prev_bounce_rate"),
            ]

            if self.query.includeRevenue:
                select.extend(
                    [
                        current_period_aggregate("sum", "session_revenue", "revenue"),
                        previous_period_aggregate("sum", "session_revenue", "previous_revenue"),
                    ]
                )

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

    # Only calculate change if both value and previous exist and previous is not zero
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
        "previous": previous if previous is not None else None,  # Explicitly handle None case
        "changeFromPreviousPct": change_from_previous_pct,
    }
