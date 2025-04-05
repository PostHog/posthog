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
from posthog.hogql.database.schema.exchange_rate import (
    revenue_sum_expression_for_events,
    revenue_expression_for_data_warehouse,
)


class WebOverviewQueryRunner(WebAnalyticsQueryRunner):
    query: WebOverviewQuery
    response: WebOverviewQueryResponse
    cached_response: CachedWebOverviewQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
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

        if self.query.conversionGoal:
            results = [
                to_data("visitors", "unit", self._unsample(row[0]), self._unsample(row[1])),
                to_data("total conversions", "unit", self._unsample(row[2]), self._unsample(row[3])),
                to_data("unique conversions", "unit", self._unsample(row[4]), self._unsample(row[5])),
                to_data("conversion rate", "percentage", row[6], row[7]),
            ]
            if self.query.includeRevenue:
                results.append(to_data("conversion revenue", "currency", row[8], row[9]))
        else:
            results = [
                to_data("visitors", "unit", self._unsample(row[0]), self._unsample(row[1])),
                to_data("views", "unit", self._unsample(row[2]), self._unsample(row[3])),
                to_data("sessions", "unit", self._unsample(row[4]), self._unsample(row[5])),
                to_data("session duration", "duration_s", row[6], row[7]),
                to_data("bounce rate", "percentage", row[8], row[9], is_increase_bad=True),
            ]
            if self.query.includeRevenue:
                results.append(to_data("revenue", "currency", row[10], row[11]))

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
        def current_period_aggregate(
            function_name: str,
            column_name: str,
            alias: str,
            params: Optional[list[ast.Expr]] = None,
            extra_args: Optional[list[ast.Expr]] = None,
        ):
            if not self.query_compare_to_date_range:
                return ast.Call(name=function_name, params=params, args=[ast.Field(chain=[column_name])])

            return self.period_aggregate(
                function_name,
                column_name,
                self.query_date_range.date_from_as_hogql(),
                self.query_date_range.date_to_as_hogql(),
                alias=alias,
                params=params,
                extra_args=extra_args,
            )

        def previous_period_aggregate(
            function_name: str,
            column_name: str,
            alias: str,
            params: Optional[list[ast.Expr]] = None,
            extra_args: Optional[list[ast.Expr]] = None,
        ):
            if not self.query_compare_to_date_range:
                return ast.Alias(alias=alias, expr=ast.Constant(value=None))

            return self.period_aggregate(
                function_name,
                column_name,
                self.query_compare_to_date_range.date_from_as_hogql(),
                self.query_compare_to_date_range.date_to_as_hogql(),
                alias=alias,
                params=params,
                extra_args=extra_args,
            )

        session_id_is_not_null = ast.Call(name="isNotNull", args=[ast.Field(chain=["session_id"])])

        if self.query.conversionGoal:
            select = [
                current_period_aggregate(
                    "uniq", "session_person_id", "unique_users", extra_args=[session_id_is_not_null]
                ),
                previous_period_aggregate(
                    "uniq", "session_person_id", "previous_unique_users", extra_args=[session_id_is_not_null]
                ),
                current_period_aggregate(
                    "sum", "conversion_count", "total_conversion_count", extra_args=[session_id_is_not_null]
                ),
                previous_period_aggregate(
                    "sum", "conversion_count", "previous_total_conversion_count", extra_args=[session_id_is_not_null]
                ),
                current_period_aggregate(
                    "uniq", "conversion_person_id", "unique_conversions", extra_args=[session_id_is_not_null]
                ),
                previous_period_aggregate(
                    "uniq", "conversion_person_id", "previous_unique_conversions", extra_args=[session_id_is_not_null]
                ),
                ast.Alias(
                    alias="conversion_rate",
                    expr=ast.Call(
                        name="divide", args=[ast.Field(chain=["unique_conversions"]), ast.Field(chain=["unique_users"])]
                    ),
                ),
                ast.Alias(
                    alias="previous_conversion_rate",
                    expr=ast.Call(
                        name="divide",
                        args=[
                            ast.Field(chain=["previous_unique_conversions"]),
                            ast.Field(chain=["previous_unique_users"]),
                        ],
                    ),
                ),
            ]
            if self.query.includeRevenue:
                select.extend(
                    [
                        current_period_aggregate(
                            "sum",
                            "session_conversion_revenue",
                            "conversion_revenue",
                            extra_args=[session_id_is_not_null],
                        ),
                        previous_period_aggregate(
                            "sum",
                            "session_conversion_revenue",
                            "previous_conversion_revenue",
                            extra_args=[session_id_is_not_null],
                        ),
                    ]
                )
        else:
            select = [
                current_period_aggregate(
                    "uniq", "session_person_id", "unique_users", extra_args=[session_id_is_not_null]
                ),
                previous_period_aggregate(
                    "uniq", "session_person_id", "previous_unique_users", extra_args=[session_id_is_not_null]
                ),
                current_period_aggregate(
                    "sum",
                    "filtered_pageview_count",
                    "total_filtered_pageview_count",
                    extra_args=[session_id_is_not_null],
                ),
                previous_period_aggregate(
                    "sum",
                    "filtered_pageview_count",
                    "previous_filtered_pageview_count",
                    extra_args=[session_id_is_not_null],
                ),
                current_period_aggregate("uniq", "session_id", "unique_sessions", extra_args=[session_id_is_not_null]),
                previous_period_aggregate(
                    "uniq", "session_id", "previous_unique_sessions", extra_args=[session_id_is_not_null]
                ),
                current_period_aggregate(
                    "avg", "session_duration", "avg_duration_s", extra_args=[session_id_is_not_null]
                ),
                previous_period_aggregate(
                    "avg", "session_duration", "prev_avg_duration_s", extra_args=[session_id_is_not_null]
                ),
                current_period_aggregate("avg", "is_bounce", "bounce_rate", extra_args=[session_id_is_not_null]),
                previous_period_aggregate("avg", "is_bounce", "prev_bounce_rate", extra_args=[session_id_is_not_null]),
            ]

            # NOTE: This won't include `session_id_is_not_null` because
            # we want to include revenue coming from Data Warehouse tables
            # and those won't contain `session_id`
            if self.query.includeRevenue:
                select.extend(
                    [
                        current_period_aggregate("sum", "session_revenue", "revenue"),
                        previous_period_aggregate("sum", "session_revenue", "previous_revenue"),
                    ]
                )

        query = ast.SelectQuery(select=select, select_from=ast.JoinExpr(table=self.inner_select))

        # If we can find some selects for DW revenue, then join it with that instead of just the inner select
        if self.data_warehouse_revenue_selects:
            query.select_from = ast.JoinExpr(
                table=ast.SelectSetQuery.create_from_queries(
                    [self.inner_select, *self.data_warehouse_revenue_selects],
                    set_operator="UNION ALL",
                )
            )

        assert isinstance(query, ast.SelectQuery)
        return query

    @cached_property
    def data_warehouse_revenue_selects(self) -> list[ast.SelectQuery]:
        if not self.include_data_warehouse_revenue:
            return []

        if not self.query.includeRevenue:
            return []

        if not self.team.revenue_config.dataWarehouseTables:
            return []

        queries: list[ast.SelectQuery] = []

        # This is a little bit complicated, but here's the gist of it:
        #
        # We need to include the same amount of columns in this select query as in the inner select query
        # It also needs to be in the exact same order because ClickHouse doesn't care about the column names
        # from subsequent queries in a SelectSetQuery, it only cares about the names of the first query
        # and then the positions of the columns in subsequent queries.
        #
        # So we need to iterate over the columns in the inner select query and create a new alias for each column.
        # Because we don't care about the value, and we actually want to ignore them in the main query,
        # we set them to `None` and then replace `session_revenue` and `start_timestamp` with the
        # revenue column and timestamp column from the data warehouse table respectively.
        for table in self.team.revenue_config.dataWarehouseTables:
            select_columns: list[ast.Expr] = []
            for select in self.inner_select.select:
                if not isinstance(select, ast.Alias):  # Guarantee type-safety
                    continue

                new_select = ast.Alias(alias=select.alias, expr=ast.Constant(value=None))

                # Only care about timestamp and revenue, keep the rest as None
                if select.alias == "start_timestamp":
                    new_select = ast.Alias(
                        alias=select.alias,
                        expr=ast.Field(chain=[table.tableName, table.timestampColumn]),
                    )
                elif select.alias == "session_revenue":
                    new_select = ast.Alias(
                        alias=select.alias,
                        expr=revenue_expression_for_data_warehouse(self.team.revenue_config, table),
                    )

                select_columns.append(new_select)

            queries.append(
                ast.SelectQuery(
                    select=select_columns,
                    select_from=ast.JoinExpr(table=ast.Field(chain=[table.tableName])),
                    where=self._periods_expression("start_timestamp"),
                )
            )

        return queries


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

    try:
        if value is not None and previous:
            change_from_previous_pct = round(100 * (value - previous) / previous)
        else:
            change_from_previous_pct = None
    except ValueError:
        change_from_previous_pct = None

    return {
        "key": key,
        "kind": kind,
        "isIncreaseBad": is_increase_bad,
        "value": value,
        "previous": previous,
        "changeFromPreviousPct": change_from_previous_pct,
    }
