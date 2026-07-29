from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional, cast

from posthog.schema import (
    CachedHogQLQueryResponse,
    DashboardFilter,
    DateRange,
    HogQLFilters,
    HogQLQuery,
    HogQLQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import INCREASED_MAX_EXECUTION_TIME_CONTEXTS, HogQLGlobalSettings
from posthog.hogql.direct_connection import INVALID_CONNECTION_ID_ERROR
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.filters import replace_filters
from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import CacheOrigin, parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.user_query_validator import validate_user_query
from posthog.hogql.variables import replace_variables

from posthog import settings as app_settings
from posthog.caching.utils import ThresholdMode, staleness_threshold_map
from posthog.clickhouse.query_tagging import tag_contains_user_hogql
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.warehouse_sources.backend.facade.models import get_direct_external_data_source_for_connection

_INFORMATION_SCHEMA_PREFIX = "system.information_schema."


def api_query_max_execution_time(team_id: int) -> Optional[int]:
    """ClickHouse max_execution_time (seconds) to impose on this team's public API queries, or None
    for no API-specific ceiling."""
    override = app_settings.API_QUERIES_MAX_EXECUTION_TIME_PER_TEAM.get(team_id)
    if override is not None:
        return override if override > 0 else None
    # Teams that predate the API limits keep the in-app budget, as do deployments that never
    # configured the limits at all.
    if not app_settings.API_QUERIES_LEGACY_TEAM_LIST or team_id in app_settings.API_QUERIES_LEGACY_TEAM_LIST:
        return None
    return app_settings.API_QUERIES_MAX_EXECUTION_TIME


def api_timeout_detail(max_execution_time: int) -> str:
    return (
        f"This query hit the {max_execution_time}-second time limit for queries run through the API. "
        "Submit it as an async query to give it more time: "
        "https://posthog.com/docs/api/queries#asynchronous-queries. "
        "You can also narrow the date range or the filters so it scans less data: "
        "https://posthog.com/docs/api/queries#writing-performant-queries"
    )


class HogQLQueryRunner(AnalyticsQueryRunner[HogQLQueryResponse]):
    query: HogQLQuery
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

    def requires_fresh_calculation(self) -> bool:
        # system.information_schema.* mirrors mutable data-catalog state (metric approval, relationship
        # acceptance, source certification). A cached row keeps reporting the pre-change status after a
        # catalog write, so recompute these queries rather than trust the query cache. Cheap to detect:
        # the schema metadata itself is fast to compute. External-connection queries never touch it.
        if self.query.connectionId:
            return False
        try:
            table_names = get_table_names(parse_select(self.query.query))
        except Exception:
            return False
        return any(name.lower().startswith(_INFORMATION_SCHEMA_PREFIX) for name in table_names)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        values: Optional[dict[str, ast.Expr]] = (
            {key: ast.Constant(value=value) for key, value in self.query.values.items()} if self.query.values else None
        )
        with self.timings.measure("parse_select"):
            parsed_select = parse_select(
                self.query.query,
                timings=self.timings,
                placeholders=values,
                cache_origin=CacheOrigin.USER,
            )

        finder = find_placeholders(parsed_select)
        with self.timings.measure("filters"):
            if self.query.filters and finder.has_filters:
                parsed_select = replace_filters(parsed_select, self.query.filters, self.team)
        if self.query.variables:
            with self.timings.measure("replace_variables"):
                parsed_select = replace_variables(parsed_select, list(self.query.variables.values()), self.team)
        if finder.placeholder_fields or finder.placeholder_expressions:
            with self.timings.measure("replace_placeholders"):
                var_dict: dict[str, Any] = {}
                var_values: dict[str, Any] = {"variables": var_dict, **values} if values else {"variables": var_dict}
                if self.query.variables:
                    for var in list(self.query.variables.values()):
                        var_dict[var.code_name] = var.value
                    parsed_select = cast(ast.SelectQuery, replace_placeholders(parsed_select, var_values))

        return parsed_select

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self.to_query()

    def _calculate(self) -> HogQLQueryResponse:
        tag_contains_user_hogql()
        api_max_execution_time = api_query_max_execution_time(self.team.pk) if self.is_query_service else None
        if api_max_execution_time is not None:
            assert self.settings is not None
            # p95 threads is 102, limiting to 60 (below global max_threads of 64)
            self.settings.max_threads = 60
            self.settings.max_execution_time = api_max_execution_time

        try:
            return self._execute()
        except ClickHouseQueryTimeOut:
            # The default copy only talks about materializing, which leaves an API caller with no way
            # to find out that the ceiling above is what killed the query. Rewrite it only when that
            # ceiling actually bound this run: execute_hogql_query raises the ceiling back to
            # HOGQL_INCREASED_MAX_EXECUTION_TIME for the contexts below, so a query that timed out
            # under one of those had a far bigger budget than we set here.
            if api_max_execution_time is None or self.limit_context in INCREASED_MAX_EXECUTION_TIME_CONTEXTS:
                raise
            raise ClickHouseQueryTimeOut(detail=api_timeout_detail(api_max_execution_time))

    def _execute(self) -> HogQLQueryResponse:
        if self.query.connectionId:
            source = get_direct_external_data_source_for_connection(
                team_id=self.team.pk, connection_id=self.query.connectionId
            )
            if source is None:
                raise ExposedHogQLError(INVALID_CONNECTION_ID_ERROR)

        if self.query.sendRawQuery and self.query.connectionId:
            return execute_hogql_query(
                query_type="HogQLQuery",
                query=self.query.query,
                filters=self.query.filters,
                modifiers=self.query.modifiers or self.modifiers,
                team=self.team,
                user=self.user,
                user_access_control=self.user_access_control,
                timings=self.timings,
                variables=self.query.variables,
                connection_id=self.query.connectionId,
                limit_context=self.limit_context,
                workload=self.workload,
                settings=self.settings,
                send_raw_query=True,
            )

        query = self.to_query()

        if self.is_query_service:
            validate_user_query(query, team=self.team)

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
            user=self.user,
            user_access_control=self.user_access_control,
            timings=self.timings,
            variables=self.query.variables,
            connection_id=self.query.connectionId,
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
