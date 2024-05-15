from datetime import timedelta
from typing import cast
from django.utils.timezone import datetime

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    CachedLogsQueryResponse,
    IntervalType,
    LogsQuery,
    LogsQueryResponse,
)


class LogsQueryRunner(QueryRunner):
    query: LogsQuery
    response: LogsQueryResponse
    cached_response: CachedLogsQueryResponse

    def to_query(self) -> ast.SelectQuery:
        return cast(
            ast.SelectQuery,
            parse_select(
                """
                    SELECT timestamp, properties.$level, properties.$msg, properties
                    FROM events
                    WHERE {where_clause}
                    ORDER BY timestamp ASC
                """,
                {"where_clause": self._where_clause()},
            ),
        )

    def to_actors_query(self) -> ast.SelectQuery:
        return self.to_query()

    def calculate(self) -> LogsQueryResponse:
        query = self.to_query()

        response = execute_hogql_query(
            query_type="LogsQuery",
            query=query,
            modifiers=self.query.modifiers or self.modifiers,
            team=self.team,
            workload=Workload.ONLINE,
            timings=self.timings,
            limit_context=self.limit_context,
        )

        results = [
            {"timestamp": log[0], "level": log[1], "msg": log[2], "properties": log[3]} for log in response.results
        ]

        return LogsQueryResponse(results=results)

    def _where_clause(self):
        filters: list[ast.Expr] = []

        # Dates
        date_range_placeholders = self._query_date_range.to_placeholders()
        filters.extend(
            [
                parse_expr(
                    "timestamp >= {date_from_with_adjusted_start_of_interval}", placeholders=date_range_placeholders
                ),
                parse_expr("timestamp <= {date_to}", placeholders=date_range_placeholders),
            ]
        )

        # Event name
        filters.append(parse_expr("event = '$log'"))

        if len(filters) == 0:
            return ast.Constant(value=True)
        elif len(filters) == 1:
            return filters[0]

        return ast.And(exprs=filters)

    @cached_property
    def _query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.minute,
            now=datetime.now(),
        )

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
