from typing import Optional, cast
from collections.abc import Callable

from posthog.hogql import ast
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedHogQLQueryResponse,
    HogQLQuery,
    HogQLQueryResponse,
    DashboardFilter,
    HogQLFilters,
    DateRange,
)


class HogQLQueryRunner(QueryRunner):
    query: HogQLQuery
    response: HogQLQueryResponse
    cached_response: CachedHogQLQueryResponse

    def to_query(self) -> ast.SelectQuery:
        if self.timings is None:
            self.timings = HogQLTimings()
        values: Optional[dict[str, ast.Expr]] = (
            {key: ast.Constant(value=value) for key, value in self.query.values.items()} if self.query.values else None
        )
        with self.timings.measure("parse_select"):
            parsed_select = parse_select(str(self.query.query), timings=self.timings)

        finder = find_placeholders(parsed_select)
        with self.timings.measure("filters"):
            if self.query.filters and finder.has_filters:
                parsed_select = replace_filters(parsed_select, self.query.filters, self.team)
        if len(finder.field_strings) > 0 or finder.has_expr_placeholders:
            with self.timings.measure("replace_placeholders"):
                parsed_select = cast(ast.SelectQuery, replace_placeholders(parsed_select, values))

        return parsed_select

    def to_actors_query(self) -> ast.SelectQuery:
        return self.to_query()

    def calculate(self) -> HogQLQueryResponse:
        query = self.to_query()
        paginator = None
        if isinstance(query, ast.SelectQuery) and not query.limit:
            paginator = HogQLHasMorePaginator.from_limit_context(limit_context=self.limit_context)
        func = cast(
            Callable[..., HogQLQueryResponse],
            execute_hogql_query if paginator is None else paginator.execute_hogql_query,
        )
        response = func(
            query_type="HogQLQuery",
            query=query,
            filters=self.query.filters,
            modifiers=self.query.modifiers or self.modifiers,
            team=self.team,
            timings=self.timings,
            limit_context=self.limit_context,
        )
        if paginator:
            response = response.model_copy(update={**paginator.response_params(), "results": paginator.results})
        return response

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        self.query.filters = self.query.filters or HogQLFilters()

        if dashboard_filter.date_to or dashboard_filter.date_from:
            if self.query.filters.dateRange is None:
                self.query.filters.dateRange = DateRange()
            self.query.filters.dateRange.date_to = dashboard_filter.date_to
            self.query.filters.dateRange.date_from = dashboard_filter.date_from

        if dashboard_filter.properties:
            self.query.filters.properties = (self.query.filters.properties or []) + dashboard_filter.properties
