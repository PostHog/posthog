from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional, cast

from posthog.schema import (
    CachedHogQLQueryResponse,
    CacheMissResponse,
    DashboardFilter,
    DateRange,
    HogQLFilters,
    HogQLQuery,
    HogQLQueryResponse,
    QueryStatusResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.direct_connection import INVALID_CONNECTION_ID_ERROR, get_direct_connection_source
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
from posthog.event_usage import AnalyticsProps
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.models import User

from products.managed_warehouse.backend.facade import query_labels as managed_warehouse_query_labels
from products.warehouse_sources.backend.facade.types import ManagedWarehouseSQLMode

_INFORMATION_SCHEMA_PREFIX = "system.information_schema."


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
        self._direct_connection_validated = False
        self._managed_warehouse_sql_mode: ManagedWarehouseSQLMode | None = None
        super().__init__(*args, **kwargs)

    # Treat SQL query caching like day insight
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + staleness_threshold_map[ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT]["day"]

    def _validate_direct_connection(self, *, user: Optional[User] = None, force: bool = False) -> None:
        if self._direct_connection_validated and not force:
            return
        managed_warehouse_sql_mode: ManagedWarehouseSQLMode | None = None
        if self.query.connectionId:
            source = get_direct_connection_source(
                self.team,
                self.query.connectionId,
                user=user if user is not None else self.user,
            )
            if source is None:
                raise ExposedHogQLError(INVALID_CONNECTION_ID_ERROR)
            if source.has_managed_warehouse_prefix:
                managed_warehouse_sql_mode = source.managed_warehouse_sql_mode
                if managed_warehouse_sql_mode == ManagedWarehouseSQLMode.UNAVAILABLE:
                    raise ExposedHogQLError(INVALID_CONNECTION_ID_ERROR)
        self._managed_warehouse_sql_mode = managed_warehouse_sql_mode
        self._direct_connection_validated = True

    def get_cache_payload(self) -> dict:
        self._validate_direct_connection()
        payload = super().get_cache_payload()
        if self._managed_warehouse_sql_mode == ManagedWarehouseSQLMode.BUILT_IN:
            payload["managed_warehouse_sql_mode"] = self._managed_warehouse_sql_mode.value
        return payload

    def query_status_labels(self) -> list[str] | None:
        self._validate_direct_connection()
        if self._managed_warehouse_sql_mode == ManagedWarehouseSQLMode.BUILT_IN:
            return [
                f"{managed_warehouse_query_labels.MANAGED_WAREHOUSE_QUERY_STATUS_LABEL_PREFIX}{self.query.connectionId}"
            ]
        return None

    def run(
        self,
        execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user: Optional[User] = None,
        query_id: Optional[str] = None,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
        cache_age_seconds: Optional[int] = None,
        analytics_props: Optional[AnalyticsProps] = None,
    ) -> HogQLQueryResponse | CachedHogQLQueryResponse | CacheMissResponse | QueryStatusResponse:
        self._validate_direct_connection(user=user, force=True)
        return super().run(
            execution_mode=execution_mode,
            user=user,
            query_id=query_id,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            cache_age_seconds=cache_age_seconds,
            analytics_props=analytics_props,
        )

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
        if (
            self.is_query_service
            and app_settings.API_QUERIES_LEGACY_TEAM_LIST
            and self.team.pk not in app_settings.API_QUERIES_LEGACY_TEAM_LIST
        ):
            assert self.settings is not None
            # p95 threads is 102, limiting to 60 (below global max_threads of 64)
            self.settings.max_threads = 60
            # p95 duration of HogQL query is 2.78sec
            self.settings.max_execution_time = 10

        self._validate_direct_connection()

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
                ch_user=self.ch_user,
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
            ch_user=self.ch_user,
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
            # The date range is one unit, so never pair the dashboard's bounds with the insight's own
            # explicitDate (matching apply_dashboard_filters.py; the base QueryRunner still keeps the
            # insight's flag when the dashboard's is None). Coerced to bool to keep the serialized
            # value at false rather than null.
            self.query.filters.dateRange.explicitDate = bool(dashboard_filter.explicitDate)

        if dashboard_filter.properties:
            self.query.filters.properties = (self.query.filters.properties or []) + dashboard_filter.properties

        if dashboard_filter.interval is not None:
            self.query.filters.interval = dashboard_filter.interval

        if dashboard_filter.breakdown_filter is not None:
            self.query.filters.breakdownFilter = dashboard_filter.breakdown_filter

        # Tri-state override: None means inherit the insight's own setting.
        if dashboard_filter.filterTestAccounts is not None:
            self.query.filters.filterTestAccounts = dashboard_filter.filterTestAccounts
