from datetime import datetime
from typing import Optional, cast
from collections.abc import Callable

from posthog import settings as app_settings
from posthog.caching.utils import ThresholdMode, staleness_threshold_map
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.utils import deserialize_hx_ast
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedHogQLQueryResponse,
    HogQLQuery,
    HogQLASTQuery,
    HogQLQueryResponse,
    DashboardFilter,
    HogQLFilters,
    DateRange,
)


class HogQLQueryRunner(QueryRunner):
    query: HogQLQuery | HogQLASTQuery
    response: HogQLQueryResponse
    cached_response: CachedHogQLQueryResponse
    settings: Optional[HogQLGlobalSettings]

    def __init__(
        self,
        *args,
        settings: Optional[HogQLGlobalSettings] = None,
        **kwargs,
    ):
        self.settings = settings or HogQLGlobalSettings()
        super().__init__(*args, **kwargs)

    # Treat SQL query caching like day insight
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + staleness_threshold_map[ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT]["day"]

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        values: Optional[dict[str, ast.Expr]] = (
            {key: ast.Constant(value=value) for key, value in self.query.values.items()} if self.query.values else None
        )
        with self.timings.measure("parse_select"):
            if isinstance(self.query, HogQLQuery):
                parsed_select = parse_select(self.query.query, timings=self.timings, placeholders=values)
            elif isinstance(self.query, HogQLASTQuery):
                parsed_select = cast(ast.SelectQuery, deserialize_hx_ast(self.query.query))

        if self.query.filters:
            with self.timings.measure("filters"):
                placeholders_in_query = find_placeholders(parsed_select)
                if "filters" in placeholders_in_query:
                    parsed_select = replace_filters(parsed_select, self.query.filters, self.team)
        return parsed_select

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
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

        if (
            self.is_query_service
            and app_settings.API_QUERIES_LEGACY_TEAM_LIST
            and self.team.pk not in app_settings.API_QUERIES_LEGACY_TEAM_LIST
        ):
            assert self.settings is not None
            # p95 threads is 102
            self.settings.max_threads = 80
            # p95 duration of HogQL query is 2.78sec
            self.settings.max_execution_time = 10

        response = func(
            query_type="HogQLQuery",
            query=query,
            filters=self.query.filters,
            modifiers=self.query.modifiers or self.modifiers,
            team=self.team,
            timings=self.timings,
            variables=self.query.variables,
            limit_context=self.limit_context,
            workload=self.workload,
            settings=self.settings,
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
