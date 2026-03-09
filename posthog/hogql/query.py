import dataclasses
from typing import ClassVar, Optional, Union, cast

import psycopg
from opentelemetry import trace

from posthog.schema import (
    HogLanguage,
    HogQLFilters,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    HogQLVariable,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext, get_default_limit_for_context
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.schema.logs import HOGQL_MAX_BYTES_TO_READ_FOR_LOGS_USER_QUERIES
from posthog.hogql.errors import ExposedHogQLError, QueryError, ResolutionError
from posthog.hogql.filters import replace_filters
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.resolver import Resolver
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.transforms.preaggregated_table_transformation import do_preaggregated_table_transforms
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.models.team import Team
from posthog.models.user import User
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME

tracer = trace.get_tracer(__name__)

POSTGRES_OID_TO_CLICKHOUSE_TYPE: dict[int, str] = {
    16: "Bool",  # bool
    20: "Int64",  # int8
    21: "Int16",  # int2
    23: "Int32",  # int4
    26: "UInt32",  # oid
    700: "Float32",  # float4
    701: "Float64",  # float8
    1082: "Date",  # date
    1114: "DateTime",  # timestamp
    1184: "DateTime64(6, 'UTC')",  # timestamptz
    1700: "Decimal",  # numeric
    17: "String",  # bytea
    19: "String",  # name
    25: "String",  # text
    1042: "String",  # bpchar
    1043: "String",  # varchar
    114: "String",  # json
    3802: "String",  # jsonb
    2950: "UUID",  # uuid
    1083: "String",  # time
    1266: "String",  # timetz
    1186: "String",  # interval
    1000: "Array(Bool)",  # bool[]
    1005: "Array(Int16)",  # int2[]
    1007: "Array(Int32)",  # int4[]
    1016: "Array(Int64)",  # int8[]
    1021: "Array(Float32)",  # float4[]
    1022: "Array(Float64)",  # float8[]
    1115: "Array(DateTime)",  # timestamp[]
    1185: "Array(DateTime64(6, 'UTC'))",  # timestamptz[]
    1182: "Array(Date)",  # date[]
    1231: "Array(Decimal)",  # numeric[]
    1009: "Array(String)",  # text[]
    1015: "Array(String)",  # varchar[]
    2951: "Array(UUID)",  # uuid[]
}


def postgres_oid_to_clickhouse_type(oid: int | None) -> str:
    if oid is None:
        return "String"

    return POSTGRES_OID_TO_CLICKHOUSE_TYPE.get(oid, "String")


def postgres_error_to_message(error: Exception) -> str:
    if isinstance(error, psycopg.Error):
        diag = getattr(error, "diag", None)
        message_primary = getattr(diag, "message_primary", None) if diag else None
        message_detail = getattr(diag, "message_detail", None) if diag else None
        if message_primary and message_detail:
            return f"{message_primary} {message_detail}"
        if message_primary:
            return message_primary

    message = str(error).strip()
    if not message:
        return "Postgres query failed."
    return message.splitlines()[0]


def validate_direct_postgres_source_config(source, team: Team):
    from posthog.temporal.data_imports.sources import SourceRegistry

    from products.data_warehouse.backend.types import ExternalDataSourceType

    if not source.is_direct_postgres:
        raise ExposedHogQLError("Invalid direct Postgres connection.")

    postgres_source = SourceRegistry.get_source(ExternalDataSourceType(source.source_type))
    config = postgres_source.parse_config(source.job_inputs or {})

    is_ssh_valid, ssh_valid_errors = postgres_source.ssh_tunnel_is_valid(config, team.pk)
    if not is_ssh_valid:
        raise ExposedHogQLError(ssh_valid_errors or "Invalid SSH tunnel configuration.")

    valid_host, host_errors = postgres_source.is_database_host_valid(
        config.host, team.pk, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
    )
    if not valid_host:
        raise ExposedHogQLError(host_errors or "Invalid Postgres host.")

    return postgres_source, config


@dataclasses.dataclass
class HogQLQueryExecutor:
    query: Union[str, ast.SelectQuery, ast.SelectSetQuery]
    team: Team
    _: dataclasses.KW_ONLY
    query_type: str = "hogql_query"
    filters: Optional[HogQLFilters] = None
    placeholders: Optional[dict[str, ast.Expr]] = None
    variables: Optional[dict[str, HogQLVariable]] = None
    workload: Workload = Workload.DEFAULT
    settings: Optional[HogQLGlobalSettings] = None
    modifiers: Optional[HogQLQueryModifiers] = None
    limit_context: Optional[LimitContext] = LimitContext.QUERY
    timings: HogQLTimings = dataclasses.field(default_factory=HogQLTimings)
    pretty: Optional[bool] = True
    context: HogQLContext = dataclasses.field(default_factory=lambda: HogQLQueryExecutor.__uninitialized_context)
    hogql_context: Optional[HogQLContext] = None
    clickhouse_prepared_ast: Optional[ast.AST] = None
    clickhouse_sql: Optional[str] = None
    direct_postgres_sql: Optional[str] = None
    direct_postgres_source_id: Optional[str] = None
    direct_postgres_values: dict[str, object] | None = None
    connection_id: Optional[str] = None
    selected_direct_source_id: Optional[str] = None
    user: Optional[User] = None

    __uninitialized_context: ClassVar[HogQLContext] = HogQLContext()

    @tracer.start_as_current_span("HogQLQueryExecutor.__post_init__")
    def __post_init__(self):
        if self.context is self.__uninitialized_context:
            self.context = HogQLContext(team_id=self.team.pk, user=self.user)

        self.query_modifiers = create_default_modifiers_for_team(self.team, self.modifiers)
        self.debug = self.modifiers is not None and self.modifiers.debug
        self.error: Optional[str] = None
        self.explain: Optional[list[str]] = None
        self.results = None
        self.types = None
        self.metadata: Optional[HogQLMetadataResponse] = None

    @tracer.start_as_current_span("HogQLQueryExecutor._parse_query")
    def _parse_query(self):
        with self.timings.measure("query"):
            if isinstance(self.query, ast.SelectQuery) or isinstance(self.query, ast.SelectSetQuery):
                self.select_query = self.query
                self.query = None
            else:
                self.select_query = parse_select(str(self.query), timings=self.timings)

    @tracer.start_as_current_span("HogQLQueryExecutor._process_variables")
    def _process_variables(self):
        with self.timings.measure("variables"):
            if self.variables and len(self.variables.keys()) > 0:
                self.select_query = replace_variables(
                    node=self.select_query, variables=list(self.variables.values()), team=self.team
                )

    @tracer.start_as_current_span("HogQLQueryExecutor._process_placeholders")
    def _process_placeholders(self):
        with self.timings.measure("replace_placeholders"):
            if not self.placeholders:
                self.placeholders = {}
            finder = find_placeholders(self.select_query)

            # Need to use the "filters" system to replace a few special placeholders
            if finder.has_filters:
                if "filters" in self.placeholders and self.filters is not None:
                    raise ValueError(f"Query contains 'filters' both as placeholder and as a query parameter.")
                self.select_query = replace_filters(self.select_query, self.filters, self.team)

            # If there are placeholders remaining
            if finder.placeholder_fields or finder.placeholder_expressions:
                self.select_query = cast(ast.SelectQuery, replace_placeholders(self.select_query, self.placeholders))

    @tracer.start_as_current_span("HogQLQueryExecutor._apply_limit")
    def _apply_limit(self):
        if self.limit_context in (LimitContext.COHORT_CALCULATION, LimitContext.SAVED_QUERY):
            self.context.limit_top_select = False

        with self.timings.measure("max_limit"):
            for one_query in extract_select_queries(self.select_query):
                if one_query.limit is None:
                    one_query.limit = ast.Constant(
                        value=get_default_limit_for_context(self.limit_context or LimitContext.QUERY)
                    )

    @tracer.start_as_current_span("HogQLQueryExecutor._apply_optimizers")
    def _apply_optimizers(self):
        if self.query_modifiers.usePreaggregatedTableTransforms:
            with self.timings.measure("preaggregated_table_transforms"):
                assert self.hogql_context is not None
                assert self.hogql_context.team is not None
                transformed_node = do_preaggregated_table_transforms(self.select_query, self.hogql_context)
                if isinstance(transformed_node, ast.SelectQuery) or isinstance(transformed_node, ast.SelectSetQuery):
                    self.select_query = transformed_node

        if self.query_modifiers.usePreaggregatedIntermediateResults:
            with self.timings.measure("daily_unique_persons_pageviews_transform"):
                assert self.hogql_context is not None
                from products.analytics_platform.backend.lazy_computation.lazy_computation_transformer import (
                    Transformer as DailyUniquePersonsPageviewsTransformer,
                )

                transformer = DailyUniquePersonsPageviewsTransformer(self.hogql_context)
                transformed_node = transformer.visit(self.select_query)
                if isinstance(transformed_node, ast.SelectQuery) or isinstance(transformed_node, ast.SelectSetQuery):
                    self.select_query = transformed_node

    @tracer.start_as_current_span("HogQLQueryExecutor._generate_hogql")
    def _generate_hogql(self):
        database = self.context.database
        if database is None or self.selected_direct_source_id is not None:
            database = Database.create_for(
                team=self.team,
                user=self.user,
                modifiers=self.query_modifiers,
                timings=self.timings,
                direct_query_source_id=self.selected_direct_source_id,
            )

        self.hogql_context = dataclasses.replace(
            self.context,
            team_id=self.team.pk,
            team=self.team,
            user=self.user,
            enable_select_queries=True,
            timings=self.timings,
            modifiers=self.query_modifiers,
            limit_context=self.limit_context,
            database=database,
        )

        self._apply_optimizers()

        with self.timings.measure("clone"):
            cloned_query = clone_expr(self.select_query, True)

        with self.timings.measure("prepare_ast_for_printing"):
            select_query_hogql = cast(
                ast.SelectQuery,
                prepare_ast_for_printing(node=cloned_query, context=self.hogql_context, dialect="hogql"),
            )

        with self.timings.measure("print_prepared_ast"):
            self.hogql = print_prepared_ast(
                select_query_hogql,
                self.hogql_context,
                "hogql",
                pretty=self.pretty if self.pretty is not None else True,
            )
            self.print_columns = []
            columns_query = (
                next(extract_select_queries(select_query_hogql))
                if isinstance(select_query_hogql, ast.SelectSetQuery)
                else select_query_hogql
            )
            for node in columns_query.select:
                if isinstance(node, ast.Alias):
                    self.print_columns.append(node.alias)
                else:
                    self.print_columns.append(
                        print_prepared_ast(
                            node=node,
                            context=self.hogql_context,
                            dialect="hogql",
                            stack=[select_query_hogql],
                        )
                    )

    def _extract_direct_postgres_sources_from_type(
        self, query_type: ast.SelectQueryType | ast.SelectSetQueryType
    ) -> set[str]:
        source_ids: set[str] = set()

        def visit_one(select_type: ast.SelectQueryType | ast.SelectSetQueryType) -> None:
            if isinstance(select_type, ast.SelectSetQueryType):
                for sub_type in select_type.types:
                    visit_one(sub_type)
                return

            for table_type in select_type.tables.values():
                if isinstance(table_type, ast.TableType) and isinstance(table_type.table, DirectPostgresTable):
                    source_ids.add(table_type.table.external_data_source_id)
                elif isinstance(table_type, ast.TableAliasType):
                    if isinstance(table_type.table_type, ast.TableType) and isinstance(
                        table_type.table_type.table, DirectPostgresTable
                    ):
                        source_ids.add(table_type.table_type.table.external_data_source_id)
                elif isinstance(table_type, ast.SelectQueryAliasType):
                    visit_one(table_type.select_query_type)
                elif isinstance(table_type, ast.SelectViewType):
                    visit_one(table_type.select_query_type)

            for anonymous_table in select_type.anonymous_tables:
                visit_one(anonymous_table)

        visit_one(query_type)
        return source_ids

    def _maybe_prepare_direct_postgres_query(self) -> None:
        query_type = self._get_select_query_type()
        if query_type is None:
            return

        direct_source_ids = self._extract_direct_postgres_sources_from_type(query_type)

        if len(direct_source_ids) == 0:
            if self.connection_id is not None:
                raise ExposedHogQLError("Table not found in the selected connection.")
            return

        if self.selected_direct_source_id is None:
            raise ExposedHogQLError("Direct Postgres queries require selecting a connection.")

        if len(direct_source_ids) > 1:
            raise ExposedHogQLError("Direct Postgres queries can only reference a single source.")

        if self.selected_direct_source_id is not None and self.selected_direct_source_id not in direct_source_ids:
            raise ExposedHogQLError("The query references a different source than the selected connection.")

        all_table_types = Resolver(context=self.hogql_context or self.context)._extract_tables_from_query_type(
            query_type
        )
        has_non_direct_tables = any(
            isinstance(table_type, ast.TableType) and not isinstance(table_type.table, DirectPostgresTable)
            for table_type in all_table_types
        )

        if has_non_direct_tables:
            raise ExposedHogQLError("Direct Postgres queries cannot be joined with PostHog or warehouse-synced tables.")

        direct_context = dataclasses.replace(
            self.context,
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            timings=self.timings,
            modifiers=self.query_modifiers,
            limit_context=self.limit_context,
            database=self.hogql_context.database if self.hogql_context else None,
        )

        direct_prepared_ast = prepare_ast_for_printing(
            node=self.select_query,
            context=direct_context,
            dialect="postgres",
        )

        self.direct_postgres_sql = print_prepared_ast(
            node=cast(ast.SelectQuery | ast.SelectSetQuery, direct_prepared_ast),
            context=direct_context,
            dialect="postgres",
            pretty=self.pretty if self.pretty is not None else True,
        )
        self.direct_postgres_values = direct_context.values
        self.direct_postgres_source_id = next(iter(direct_source_ids))

    def _should_use_direct_postgres(self) -> bool:
        try:
            query_type = self._get_select_query_type()
        except (QueryError, ResolutionError, AttributeError):
            return False
        if query_type is None:
            return False

        direct_source_ids = self._extract_direct_postgres_sources_from_type(query_type)
        if len(direct_source_ids) == 0:
            return False

        if len(direct_source_ids) > 1:
            raise ExposedHogQLError("Direct Postgres queries can only reference a single source.")

        all_table_types = Resolver(context=self.hogql_context or self.context)._extract_tables_from_query_type(
            query_type
        )
        has_non_direct_tables = any(
            isinstance(table_type, ast.TableType) and not isinstance(table_type.table, DirectPostgresTable)
            for table_type in all_table_types
        )

        if has_non_direct_tables:
            return False

        return True

    def _get_select_query_type(self) -> ast.SelectQueryType | ast.SelectSetQueryType | None:
        if self.select_query.type is not None:
            return self.select_query.type

        resolved_query = Resolver(context=self.hogql_context or self.context, dialect="hogql").visit(
            clone_expr(self.select_query, True)
        )

        if isinstance(resolved_query, ast.SelectQuery) or isinstance(resolved_query, ast.SelectSetQuery):
            return resolved_query.type

        return None

    def _execute_direct_postgres_query(self) -> None:
        assert self.direct_postgres_sql is not None
        assert self.direct_postgres_source_id is not None

        from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

        source = (
            ExternalDataSource.objects.get(team=self.team, id=self.connection_id)
            if self.connection_id is not None
            else ExternalDataSource.objects.get(team=self.team, id=self.direct_postgres_source_id)
        )
        postgres_source, source_config = validate_direct_postgres_source_config(source, self.team)

        try:
            with postgres_source.with_ssh_tunnel(source_config) as (host, port):
                with psycopg.connect(
                    host=host,
                    port=port,
                    dbname=source_config.database,
                    user=source_config.user,
                    password=source_config.password,
                    sslmode="prefer",
                    options="-c default_transaction_read_only=on",
                ) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(self.direct_postgres_sql, self.direct_postgres_values or None)
                        results = cursor.fetchall()
                        description = cursor.description or []
        except Exception as error:
            if self.debug:
                self.results = []
                self.error = postgres_error_to_message(error)
                self.types = []
                return
            raise ExposedHogQLError(postgres_error_to_message(error)) from error

        self.results = results
        self.types = [
            (column.name, postgres_oid_to_clickhouse_type(getattr(column, "type_code", None))) for column in description
        ]

    @tracer.start_as_current_span("HogQLQueryExecutor._generate_clickhouse_sql")
    def _generate_clickhouse_sql(self):
        settings = self.settings or HogQLGlobalSettings()
        if self.limit_context in (
            LimitContext.EXPORT,
            LimitContext.COHORT_CALCULATION,
            LimitContext.QUERY_ASYNC,
            LimitContext.SAVED_QUERY,
            LimitContext.RETENTION,
            LimitContext.POSTHOG_AI,
        ):
            settings.max_execution_time = max(settings.max_execution_time or 0, HOGQL_INCREASED_MAX_EXECUTION_TIME)

        if self.query_modifiers.formatCsvAllowDoubleQuotes is not None:
            settings.format_csv_allow_double_quotes = self.query_modifiers.formatCsvAllowDoubleQuotes
        if self.query_modifiers.forceClickhouseDataSkippingIndexes:
            settings.force_data_skipping_indices = self.query_modifiers.forceClickhouseDataSkippingIndexes

        try:
            self.clickhouse_context = dataclasses.replace(
                self.context,
                team_id=self.team.pk,
                team=self.team,
                user=self.user,
                enable_select_queries=True,
                timings=self.timings,
                modifiers=self.query_modifiers,
                limit_context=self.limit_context,
                # it's valid to reuse the hogql DB because the modifiers are the same,
                # and if we don't we end up creating the virtual DB twice per query
                database=self.hogql_context.database if self.hogql_context else None,
            )
            with self.timings.measure("prepare_ast_for_printing"):
                self.clickhouse_prepared_ast = prepare_ast_for_printing(
                    node=self.select_query,
                    context=self.clickhouse_context,
                    dialect="clickhouse",
                    settings=settings,
                )

            # Apply log-specific byte limits for user HogQL queries to prevent expensive full scans.
            # Internal runners (LogsQueryRunner, etc.) use different query_types and set their own limits.
            if self.clickhouse_context.workload == Workload.LOGS and self.query_type == "HogQLQuery":
                if settings.max_bytes_to_read is None:
                    settings.max_bytes_to_read = HOGQL_MAX_BYTES_TO_READ_FOR_LOGS_USER_QUERIES
                if settings.read_overflow_mode is None:
                    settings.read_overflow_mode = "throw"

            with self.timings.measure("print_prepared_ast"):
                if self.clickhouse_prepared_ast is None:
                    self.clickhouse_sql = ""
                else:
                    self.clickhouse_sql = print_prepared_ast(
                        node=self.clickhouse_prepared_ast,
                        context=self.clickhouse_context,
                        dialect="clickhouse",
                        settings=settings,
                        pretty=self.pretty if self.pretty is not None else True,
                    )
        except Exception as e:
            if self.debug:
                self.clickhouse_sql = ""
                if isinstance(e, ExposedCHQueryError | ExposedHogQLError):
                    self.error = str(e)
                else:
                    self.error = "Unknown error"
            else:
                raise

    @tracer.start_as_current_span("HogQLQueryExecutor._execute_clickhouse_query")
    def _execute_clickhouse_query(self):
        assert self.clickhouse_sql
        timings_dict = self.timings.to_dict()
        with self.timings.measure("clickhouse_execute"):
            tag_queries(
                team_id=self.team.pk,
                query_type=self.query_type,
                has_joins="JOIN" in self.clickhouse_sql,
                has_json_operations="JSONExtract" in self.clickhouse_sql or "JSONHas" in self.clickhouse_sql,
                timings=timings_dict,
                modifiers=(
                    {k: v for k, v in self.modifiers.model_dump().items() if v is not None} if self.modifiers else {}
                ),
            )

            # Use workload detected during AST resolution, falling back to explicitly set workload
            workload = self.workload
            if workload == Workload.DEFAULT and self.clickhouse_context.workload is not None:
                workload = self.clickhouse_context.workload

            try:
                self.results, self.types = sync_execute(
                    self.clickhouse_sql,
                    self.clickhouse_context.values,
                    with_column_types=True,
                    workload=workload,
                    team_id=self.team.pk,
                    readonly=True,
                )
            except Exception as e:
                if self.debug:
                    self.results = []
                    if isinstance(e, ExposedCHQueryError | ExposedHogQLError):
                        self.error = str(e)
                    else:
                        self.error = "Unknown error"
                else:
                    raise

        if self.debug and self.error is None:  # If the query errored, explain will fail as well.
            with self.timings.measure("explain"):
                # nosemgrep: clickhouse-injection-taint - HogQL-compiled SQL, values in context
                explain_results = sync_execute(
                    f"EXPLAIN {self.clickhouse_sql}",
                    self.clickhouse_context.values,
                    with_column_types=True,
                    workload=workload,
                    team_id=self.team.pk,
                    readonly=True,
                )
                self.explain = [str(r[0]) for r in explain_results[0]]
            with self.timings.measure("metadata"):
                from posthog.hogql.metadata import get_hogql_metadata

                self.metadata = get_hogql_metadata(
                    HogQLMetadata(language=HogLanguage.HOG_QL, query=self.hogql, debug=True),
                    self.team,
                    user=self.user,
                    hogql_ast=self.select_query,
                    clickhouse_prepared_ast=self.clickhouse_prepared_ast,
                    clickhouse_sql=self.clickhouse_sql,
                )

    @tracer.start_as_current_span("HogQLQueryExecutor.generate_clickhouse_sql")
    def generate_clickhouse_sql(self) -> tuple[str, HogQLContext]:
        self._parse_query()
        self._process_variables()
        self._process_placeholders()
        self._apply_limit()
        with self.timings.measure("_generate_hogql"):
            self._generate_hogql()
        if self.connection_id is not None or self._should_use_direct_postgres():
            self._maybe_prepare_direct_postgres_query()
            if self.direct_postgres_sql is not None:
                return self.direct_postgres_sql, self.context
        with self.timings.measure("_generate_clickhouse_sql"):
            self._generate_clickhouse_sql()
        assert self.clickhouse_sql
        return self.clickhouse_sql, self.clickhouse_context

    @tracer.start_as_current_span("HogQLQueryExecutor.execute")
    def execute(self) -> HogQLQueryResponse:
        self._parse_query()
        self._process_variables()
        self._process_placeholders()
        self._apply_limit()
        with self.timings.measure("_generate_hogql"):
            self._generate_hogql()

        if self.connection_id is not None or self._should_use_direct_postgres():
            self._maybe_prepare_direct_postgres_query()
        else:
            with self.timings.measure("_generate_clickhouse_sql"):
                self._generate_clickhouse_sql()

        if self.direct_postgres_sql is not None:
            self._execute_direct_postgres_query()
        elif self.clickhouse_sql is not None:
            self._execute_clickhouse_query()

        return HogQLQueryResponse(
            query=self.query,
            hogql=self.hogql,
            clickhouse=self.direct_postgres_sql or self.clickhouse_sql,
            error=self.error,
            timings=self.timings.to_list(),
            results=self.results,
            columns=self.print_columns,
            types=self.types,
            modifiers=self.query_modifiers,
            explain=self.explain,
            metadata=self.metadata,
        )


def execute_hogql_query(*args, **kwargs) -> HogQLQueryResponse:
    return HogQLQueryExecutor(*args, **kwargs).execute()
