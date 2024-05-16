from datetime import timedelta
from typing import cast
from dateutil.parser import isoparse
from django.utils.timezone import datetime

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    CachedLogsQueryResponse,
    IntervalType,
    LogsQuery,
    LogsQueryResponse,
    LogsQueryResult,
)
from posthog.utils import relative_date_parse


class LogsQueryRunner(QueryRunner):
    query: LogsQuery
    response: LogsQueryResponse
    cached_response: CachedLogsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )

    def to_query(self) -> ast.SelectQuery:
        return cast(
            ast.SelectQuery,
            parse_select(
                """
                    SELECT uuid, distinct_id, event, timestamp, properties.$level, properties.$msg, properties.$namespace, properties
                    FROM events
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                """,
                {"where_clause": self._where_clause()},
            ),
        )

    def to_actors_query(self) -> ast.SelectQuery:
        return self.to_query()

    def calculate(self) -> LogsQueryResponse:
        query = self.to_query()

        response = self.paginator.execute_hogql_query(
            query_type="LogsQuery",
            query=query,
            modifiers=self.query.modifiers or self.modifiers,
            team=self.team,
            workload=Workload.ONLINE,
            timings=self.timings,
            limit_context=self.limit_context,
        )

        results: list[LogsQueryResult] = [
            LogsQueryResult(
                uuid=str(log[0]),
                distinct_id=log[1],
                event=log[2],
                timestamp=str(log[3]),
                level=log[4],
                msg=log[5],
                namespace=log[6],
                properties=log[7],
            )
            for log in response.results
        ]

        return LogsQueryResponse(results=results, **self.paginator.response_params())

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

        # Before
        if self.query.before is not None:
            before = self.query.before
            try:
                parsed_date = isoparse(before)
            except ValueError:
                parsed_date = relative_date_parse(before, self.team.timezone_info)
            filters.append(
                parse_expr(
                    "timestamp < {timestamp}",
                    {"timestamp": ast.Constant(value=parsed_date)},
                    timings=self.timings,
                )
            )

        # After
        if self.query.after is not None:
            after = self.query.after
            if after != "all":
                try:
                    parsed_date = isoparse(after)
                except ValueError:
                    parsed_date = relative_date_parse(after, self.team.timezone_info)
                filters.append(
                    parse_expr(
                        "timestamp > {timestamp}",
                        {"timestamp": ast.Constant(value=parsed_date)},
                        timings=self.timings,
                    )
                )

        # Event name
        filters.append(parse_expr("event = '$log'"))

        # Search term
        if self.query.searchTerm is not None:
            filters.append(
                parse_expr(
                    """
                        or(
                            multiSearchAnyCaseInsensitive(properties.$msg, [{term}]) = 1,
                            multiSearchAnyCaseInsensitive(properties.$namespace, [{term}]) = 1
                        )
                    """,
                    {"term": ast.Constant(value=self.query.searchTerm)},
                )
            )

        # Properties
        if self.query.properties is not None and self.query.properties != []:
            filters.append(property_to_expr(self.query.properties, self.team))

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
