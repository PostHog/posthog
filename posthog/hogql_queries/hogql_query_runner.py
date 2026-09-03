from collections.abc import Callable
from datetime import datetime
from functools import cached_property
from typing import Any, Optional, cast

import structlog

from posthog.schema import (
    CachedHogQLQueryResponse,
    CacheMissResponse,
    DashboardFilter,
    DateRange,
    EventsScanWarning,
    HogQLFilters,
    HogQLQuery,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    QueryStatusResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.activity_log_visibility import activity_log_visibility_policy_version
from posthog.hogql.direct_connection import INVALID_CONNECTION_ID_ERROR, get_direct_connection_source
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.events_scan import events_scan_warnings
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
from posthog.hogql_queries.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.models import User
from posthog.models.activity_logging.retention import get_activity_log_lookback_restriction

from products.managed_warehouse.backend.facade import query_labels as managed_warehouse_query_labels
from products.warehouse_sources.backend.facade.types import ManagedWarehouseSQLMode

_INFORMATION_SCHEMA_PREFIX = "system.information_schema."
_ACTIVITY_LOGS_TABLE = "system.activity_logs"


logger = structlog.get_logger(__name__)


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
        self._direct_engine: str | None = None
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
        direct_engine: str | None = None
        if self.query.connectionId:
            source = get_direct_connection_source(
                self.team,
                self.query.connectionId,
                user=user if user is not None else self.user,
            )
            if source is None:
                raise ExposedHogQLError(INVALID_CONNECTION_ID_ERROR)
            direct_engine = source.direct_engine
            if source.has_managed_warehouse_prefix:
                managed_warehouse_sql_mode = source.managed_warehouse_sql_mode
                if managed_warehouse_sql_mode == ManagedWarehouseSQLMode.UNAVAILABLE:
                    raise ExposedHogQLError(INVALID_CONNECTION_ID_ERROR)
        self._managed_warehouse_sql_mode = managed_warehouse_sql_mode
        self._direct_engine = direct_engine
        self._direct_connection_validated = True

    def get_cache_payload(self) -> dict:
        self._validate_direct_connection()
        payload = super().get_cache_payload()
        if self._managed_warehouse_sql_mode == ManagedWarehouseSQLMode.BUILT_IN:
            payload["managed_warehouse_sql_mode"] = self._managed_warehouse_sql_mode.value
        if self._modifiers_override_provided and self.query.modifiers is not None:
            # Old workers preferred query modifiers while new workers prefer the constructor override.
            # Keep their cached results apart during a rolling deploy.
            payload["hogql_modifier_precedence"] = "runner"

        # Both activity-log guards print into the query, so a cache lookup returns before either runs.
        # `requires_fresh_calculation` below keeps a stored result from being served in every mode that may
        # calculate. CACHE_ONLY_NEVER_CALCULATE is the mode it cannot reach: that one returns a stored
        # result however stale it is, so the key carries what the guards depend on.
        if _ACTIVITY_LOGS_TABLE in self._queried_table_names:
            # Nothing else in the key tracks the visibility rules. Varying on their fingerprint means a
            # result stored under the previous rules stops being served once they change.
            payload["activity_log_visibility_policy"] = activity_log_visibility_policy_version()

            # The retention floor moves with the clock, so a result stored inside the window would outlive
            # it. Bucketing by the hour bounds a cache-only read to rows at most an hour past the floor,
            # rather than for as long as the entry lives, and a downgrade moves the floor by days, so this
            # covers a plan change too.
            floor = get_activity_log_lookback_restriction(self.team.organization)
            if floor is not None:
                payload["activity_log_retention_floor_hour"] = floor.strftime("%Y-%m-%dT%H")

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
        #
        # system.activity_logs is floored to the organization's retention window, which moves with the
        # clock, so a stored row outlives the entitlement that let it be read. Recompute rather than
        # serve one back.
        table_names = self._queried_table_names
        return any(name.lower().startswith(_INFORMATION_SCHEMA_PREFIX) for name in table_names) or (
            _ACTIVITY_LOGS_TABLE in table_names
        )

    @cached_property
    def _queried_table_names(self) -> set[str]:
        """Tables this query names, or empty when it is unparseable or reads an external connection.

        Names only, so a table reached through a saved view is absent: the resolver inlines the view's
        definition after the cache lookup. The printed guards still apply on that path, so what a read
        through a view misses is the cache partitioning, not the enforcement. Following view definitions
        here would put a saved-query lookup in front of every HogQL query's cache key, and the rest of
        the fingerprinting in `queried_access_controlled_resources` stops at the same boundary.

        Cached because the freshness check and the cache key both need it, and neither rewrites the query
        text (dashboard filters and variables are applied at `to_query` time).
        """
        if self.query.connectionId:
            return set()
        try:
            return set(get_table_names(parse_select(self.query.query)))
        except Exception:
            return set()

    def _parse_query(self) -> tuple[ast.SelectQuery | ast.SelectSetQuery, Optional[dict[str, ast.Expr]]]:
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
        return parsed_select, values

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._expand_query(self.query.filters)

    def _expand_query(self, filters: HogQLFilters | None) -> ast.SelectQuery | ast.SelectSetQuery:
        """The query as it runs, with `filters`, variables and placeholders applied."""
        parsed_select, values = self._parse_query()

        finder = find_placeholders(parsed_select)
        with self.timings.measure("filters"):
            if filters and finder.has_filters:
                # Resolve {filters} against the shared database so a filtered query builds the schema
                # once, instead of replace_filters building a throwaway one. With a connection id the
                # schema is the external connection's, so keep the per-call build there.
                database = self.shared_database if self.query.connectionId is None else None
                parsed_select = replace_filters(parsed_select, filters, self.team, database)
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

        query = self._parse_query()[0] if self._direct_engine == "trino" else self.to_query()

        if self.is_query_service:
            validate_user_query(query, team=self.team)

        paginator = None
        if isinstance(query, ast.SelectQuery) and not query.limit:
            paginator = HogQLHasMorePaginator.from_limit_context(limit_context=self.limit_context)
        func = cast(
            Callable[..., HogQLQueryResponse],
            execute_hogql_query if paginator is None else paginator.execute_hogql_query,
        )

        context_kwargs: dict[str, Any] = {}
        if self.query.connectionId is None:
            # With a connection id the executor builds its own connection-scoped database,
            # so the shared one would be built for nothing.
            context_kwargs["context"] = self.build_hogql_context()
        # Non-direct queries must print with the same effective modifiers that built the shared database.
        execution_modifiers: Optional[HogQLQueryModifiers] = self.modifiers
        if self._direct_engine == "trino":
            # Pure compilation validates only the modifiers the caller supplied. Team defaults
            # contain Django-only settings and must not make an otherwise pure query fail.
            execution_modifiers = self.query.modifiers
        response = func(
            query_type="HogQLQuery",
            query=query,
            filters=self.query.filters,
            modifiers=execution_modifiers,
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
            **context_kwargs,
        )
        if paginator:
            response = response.model_copy(update={**paginator.response_params(), "results": paginator.results})
        scan_warnings = self._events_scan_warnings(query)
        if scan_warnings:
            response.warnings = [*(response.warnings or []), *scan_warnings]
        return response

    def _events_scan_warnings(self, query: ast.SelectQuery | ast.SelectSetQuery) -> list[EventsScanWarning]:
        """Advisory warnings on the query that runs, with `{filters}` and variables applied: what ClickHouse
        reads is what counts, whichever part of the UI put the filter there. An external connection has no
        events table."""
        if self.query.connectionId is not None:
            return []
        try:
            as_written, _ = self._parse_query()
            without_test_accounts = None
            if self.query.filters and find_placeholders(as_written).has_filters:
                without_test_accounts = (
                    self._expand_query(self.query.filters.model_copy(update={"filterTestAccounts": False}))
                    if self.query.filters.filterTestAccounts
                    else query
                )
            return events_scan_warnings(query, self.shared_database, as_written, without_test_accounts)
        except Exception:
            logger.exception("hogql_events_scan_check_failed", team_id=self.team.pk)
            return []

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
