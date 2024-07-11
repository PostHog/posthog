from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    HogQLFilters,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
    EventsQuery,
    CachedErrorTrackingQueryResponse,
)
from posthog.hogql_queries.events_query_runner import EventsQueryRunner


class ErrorTrackingQueryRunner(QueryRunner):
    query: ErrorTrackingQuery
    response: ErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator
    cached_response: CachedErrorTrackingQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset if self.query.offset else None,
        )

    def to_query(self) -> ast.SelectQuery:
        where = f"properties.$exception_type = '{self.query.fingerprint}'" if self.query.fingerprint else None

        properties = self.query.filterGroup.values if self.query.filterGroup else None

        direction = "ASC" if self.query.order == "first_seen" else "DESC"
        orderBy = f"{self.query.order} {direction}" if self.query.order else None

        runner = EventsQueryRunner(
            query=EventsQuery(
                select=self.query.select,
                where=where,
                # after=self.query.dateRange.date_from,
                # before=self.query.dateRange.date_to,
                event="$exception",
                kind="EventQuery",
                orderBy=orderBy,
                properties=properties,
                filterTestAccounts=self.query.filterTestAccounts,
            ),
            team=self.team,
        )

        return runner.to_query()

    def calculate(self):
        query_result = self.paginator.execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            query_type="ErrorTrackingQuery",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            filters=(
                HogQLFilters(
                    dateRange=self.query.dateRange,
                    filterTestAccounts=self.query.filterTestAccounts,
                    # properties=self.query.properties,
                )
            ),
        )

        return ErrorTrackingQueryResponse(
            columns=query_result.columns,
            results=query_result.results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
