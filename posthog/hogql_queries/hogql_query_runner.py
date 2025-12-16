import re
import dataclasses
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional, cast

from django.db import connection

from posthog.schema import (
    CachedHogQLQueryResponse,
    DashboardFilter,
    DateRange,
    HogLanguage,
    HogQLASTQuery,
    HogQLFilters,
    HogQLMetadata,
    HogQLQuery,
    HogQLQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.filters import replace_filters
from posthog.hogql.helpers import parse_postgres_directive, uses_postgres_dialect
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import HogQLQueryExecutor, execute_hogql_query
from posthog.hogql.utils import deserialize_hx_ast
from posthog.hogql.variables import replace_variables

from posthog import settings as app_settings
from posthog.caching.utils import ThresholdMode, staleness_threshold_map
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner


class HogQLQueryRunner(AnalyticsQueryRunner[HogQLQueryResponse]):
    query: HogQLQuery | HogQLASTQuery
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

        override = self._get_cache_age_override(last_refresh)
        if override is not None:
            return override

        return last_refresh + staleness_threshold_map[ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT]["day"]

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        values: Optional[dict[str, ast.Expr]] = (
            {key: ast.Constant(value=value) for key, value in self.query.values.items()} if self.query.values else None
        )
        with self.timings.measure("parse_select"):
            if isinstance(self.query, HogQLQuery):
                parsed_select = parse_select(
                    self.query.query,
                    timings=self.timings,
                    placeholders=values,
                    allow_reserved_identifiers=uses_postgres_dialect(self.query.query),
                )
            elif isinstance(self.query, HogQLASTQuery):
                parsed_select = cast(ast.SelectQuery, deserialize_hx_ast(self.query.query))

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
                        var_values["variables"][var.code_name] = var.value
                    parsed_select = cast(ast.SelectQuery, replace_placeholders(parsed_select, var_values))

        return parsed_select

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self.to_query()

    def _calculate(self) -> HogQLQueryResponse:
        if isinstance(self.query, HogQLQuery) and uses_postgres_dialect(self.query.query):
            return self._calculate_postgres()

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
            # p95 threads is 102, limiting to 60 (below global max_threads of 64)
            self.settings.max_threads = 60
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

    def _calculate_postgres(self) -> HogQLQueryResponse:
        from posthog.hogql.errors import ExposedHogQLError
        from posthog.hogql.metadata import get_hogql_metadata

        # Parse the directive to check for external source
        query_str = self.query.query if isinstance(self.query, HogQLQuery) else None
        directive = parse_postgres_directive(query_str)

        if directive.is_direct:
            direct_query = re.sub(r"^\s*--\s*direct(?::[^\n]+)?\s*\n?", "", query_str or "", flags=re.IGNORECASE)

            results: list[Any] = []
            columns: list[str] = []
            with self.timings.measure("postgres_execute"):
                if directive.source_id:
                    results, columns = self._execute_external_postgres(directive.source_id, direct_query)
                else:
                    with connection.cursor() as cursor:
                        cursor.execute(direct_query)
                        columns = [col[0] for col in cursor.description] if cursor.description else []
                        results = cursor.fetchall()

            return HogQLQueryResponse(
                query=self.query.query if isinstance(self.query, HogQLQuery) else None,
                hogql=None,
                clickhouse=None,
                postgres=direct_query,
                error=None,
                timings=self.timings.to_list(),
                results=results,
                columns=columns,
                modifiers=self.query.modifiers or self.modifiers,
                metadata=None,
            )

        executor = HogQLQueryExecutor(
            query=self.to_query(),
            team=self.team,
            query_type="hogql_query",
            filters=None,
            variables=None,
            placeholders=None,
            workload=self.workload,
            modifiers=self.query.modifiers or self.modifiers,
            limit_context=self.limit_context,
            settings=self.settings,
            timings=self.timings,
        )

        executor._parse_query()
        executor._process_variables()
        executor._process_placeholders()
        executor._apply_limit()
        executor._generate_hogql(dialect="postgres")

        postgres_context = dataclasses.replace(
            executor.context,
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            timings=executor.timings,
            modifiers=executor.query_modifiers,
            limit_context=self.limit_context,
        )

        metadata = None
        postgres_sql = ""
        try:
            with executor.timings.measure("prepare_and_print_ast"):
                postgres_sql, prepared_ast = prepare_and_print_ast(
                    executor.select_query,
                    context=postgres_context,
                    dialect="postgres",
                    pretty=executor.pretty if executor.pretty is not None else True,
                )
        except Exception as e:
            if executor.debug:
                executor.error = str(e) if isinstance(e, ExposedHogQLError) else "Unknown error"
                postgres_sql = ""
                prepared_ast = None
            else:
                raise

        results: list[Any] = []
        columns: list[str] = []
        if executor.error is None:
            with executor.timings.measure("postgres_execute"):
                if directive.source_id:
                    # Direct query to external Postgres source
                    results, columns = self._execute_external_postgres(directive.source_id, postgres_sql)
                else:
                    # Regular Django DB connection
                    with connection.cursor() as cursor:
                        print(postgres_sql)  # noqa: T201
                        cursor.execute(postgres_sql)
                        columns = [col[0] for col in cursor.description] if cursor.description else []
                        results = cursor.fetchall()

        if executor.debug and executor.error is None:
            metadata = get_hogql_metadata(
                HogQLMetadata(
                    language=HogLanguage.HOG_QL_POSTGRES,
                    query=self.query.query if isinstance(self.query, HogQLQuery) else executor.hogql or "",
                    debug=True,
                    filters=self.query.filters,
                    variables=self.query.variables,
                    globals=self.query.values,
                ),
                self.team,
                executor.select_query,
                prepared_ast,
                postgres_sql,
            )

        return HogQLQueryResponse(
            query=self.query.query if isinstance(self.query, HogQLQuery) else executor.hogql,
            hogql=executor.hogql,
            clickhouse=None,
            postgres=postgres_sql,
            error=executor.error,
            timings=executor.timings.to_list(),
            results=results,
            columns=columns,
            modifiers=self.query.modifiers or self.modifiers,
            metadata=metadata,
        )

    def _execute_external_postgres(self, source_id: str, sql: str) -> tuple[list[Any], list[str]]:
        """Execute a query against an external Postgres database."""
        import psycopg2

        from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

        source = ExternalDataSource.objects.get(source_id=source_id, team_id=self.team.pk)
        job_inputs = source.job_inputs or {}

        host = job_inputs.get("host")
        port = job_inputs.get("port", 5432)
        database = job_inputs.get("database")
        user = job_inputs.get("user")
        password = job_inputs.get("password")

        print(f"Connecting to external Postgres: {host}:{port}/{database}")  # noqa: T201
        print(sql)  # noqa: T201

        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                columns = [col.name for col in cursor.description] if cursor.description else []
                results = cursor.fetchall()
                return results, columns
        finally:
            conn.close()

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        self.query.filters = self.query.filters or HogQLFilters()

        if dashboard_filter.date_to or dashboard_filter.date_from:
            if self.query.filters.dateRange is None:
                self.query.filters.dateRange = DateRange()
            self.query.filters.dateRange.date_to = dashboard_filter.date_to
            self.query.filters.dateRange.date_from = dashboard_filter.date_from

        if dashboard_filter.properties:
            self.query.filters.properties = (self.query.filters.properties or []) + dashboard_filter.properties
