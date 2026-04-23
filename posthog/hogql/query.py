import dataclasses
from datetime import date, datetime
from typing import ClassVar, Literal, Optional, TypedDict, Union, cast

import psycopg
from opentelemetry import trace
from psycopg.types.datetime import DateLoader

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
from posthog.hogql.constants import (
    HogQLGlobalSettings,
    LimitContext,
    get_default_hogql_global_settings,
    get_default_limit_for_context,
)
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.schema.logs import HOGQL_MAX_BYTES_TO_READ_FOR_LOGS_USER_QUERIES
from posthog.hogql.direct_connection import (
    get_direct_connection_source_none_or_raise,
    validate_direct_postgres_source_config,
)
from posthog.hogql.errors import ExposedHogQLError, QueryError, ResolutionError
from posthog.hogql.escape_sql import escape_postgres_identifier
from posthog.hogql.filters import replace_filters
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.resolver import Resolver
from posthog.hogql.resolver_utils import extract_base_table_types, extract_select_queries
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.transforms.preaggregated_table_transformation import do_preaggregated_table_transforms
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME

tracer = trace.get_tracer(__name__)
DIRECT_POSTGRES_CONNECT_TIMEOUT_SECONDS = 15
DIRECT_POSTGRES_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600

POSTGRES_OID_TO_CLICKHOUSE_TYPE: dict[int, str] = {
    16: "Bool",
    20: "Int64",
    21: "Int16",
    23: "Int32",
    26: "UInt32",
    700: "Float32",
    701: "Float64",
    1082: "Date",
    1114: "DateTime",
    1184: "DateTime64(6, 'UTC')",
    1700: "Decimal",
    17: "String",
    19: "String",
    25: "String",
    1042: "String",
    1043: "String",
    114: "String",
    3802: "String",
    2950: "UUID",
    1083: "String",
    1266: "String",
    1186: "String",
    1000: "Array(Bool)",
    1005: "Array(Int16)",
    1007: "Array(Int32)",
    1016: "Array(Int64)",
    1021: "Array(Float32)",
    1022: "Array(Float64)",
    1115: "Array(DateTime)",
    1185: "Array(DateTime64(6, 'UTC'))",
    1182: "Array(Date)",
    1231: "Array(Decimal)",
    1009: "Array(String)",
    1015: "Array(String)",
    2951: "Array(UUID)",
}


class PostgresConnectionKwargs(TypedDict, total=False):
    host: str
    port: int
    dbname: str
    user: str
    password: str
    connect_timeout: int
    sslmode: str
    options: str
    sslcert: str
    sslkey: str
    sslrootcert: str


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


def direct_postgres_session_setup_sql(
    schema: str | None,
    connection_metadata: dict[str, object] | None = None,
    host: str | None = None,
) -> str | None:
    engine = connection_metadata.get("engine") if isinstance(connection_metadata, dict) else None
    database = connection_metadata.get("database") if isinstance(connection_metadata, dict) else None
    normalized_schema = schema.strip() if isinstance(schema, str) and schema.strip() else None

    if engine == "duckdb" or (host is not None and host.endswith(".postwh.com")):
        if normalized_schema:
            quoted_schema = escape_postgres_identifier(normalized_schema)
            return f"USE {quoted_schema}"
        if isinstance(database, str) and database.strip():
            quoted_database = escape_postgres_identifier(database.strip())
            return f"USE {quoted_database}"
        return None

    if not normalized_schema:
        return None

    quoted_schema = escape_postgres_identifier(normalized_schema)
    return f"SET search_path TO {quoted_schema}"


def parse_lenient_direct_postgres_date(value: str) -> date:
    trimmed = value.strip()

    try:
        return date.fromisoformat(trimmed)
    except ValueError:
        pass

    normalized = trimmed[:-1] + "+00:00" if trimmed.endswith("Z") else trimmed
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass

    if len(trimmed) >= 10:
        return date.fromisoformat(trimmed[:10])

    raise ValueError(f"Unable to parse date value: {value!r}")


class LenientDirectPostgresDateLoader(DateLoader):
    """Handle non-standard DATE text values returned by DuckDB's Postgres wire."""

    def load(self, data) -> date:
        try:
            return super().load(data)
        except psycopg.DataError as exc:
            try:
                return parse_lenient_direct_postgres_date(bytes(data).decode("utf8", "replace"))
            except ValueError:
                raise exc from None


def get_runtime_direct_postgres_connection_metadata(
    connection: psycopg.Connection,
    connection_metadata: dict[str, object] | None = None,
) -> dict[str, object] | None:
    runtime_connection_metadata = dict(connection_metadata) if isinstance(connection_metadata, dict) else {}
    engine = runtime_connection_metadata.get("engine")
    database = runtime_connection_metadata.get("database")

    if engine is not None and isinstance(database, str) and database.strip():
        return runtime_connection_metadata

    metadata_cursor = connection.execute("SELECT current_database(), version()")
    row = metadata_cursor.fetchone()
    current_database = str(row[0]).strip() if row and row[0] is not None else None
    version = str(row[1]) if row and len(row) > 1 and row[1] is not None else ""

    if current_database and "database" not in runtime_connection_metadata:
        runtime_connection_metadata["database"] = current_database

    if "engine" not in runtime_connection_metadata:
        runtime_connection_metadata["engine"] = (
            "duckdb" if "duckdb" in version.lower() or "duckgres" in version.lower() else "postgres"
        )

    return runtime_connection_metadata or None


def should_hydrate_runtime_direct_postgres_connection_metadata(
    schema: str | None,
    connection_metadata: dict[str, object] | None = None,
) -> bool:
    normalized_schema = schema.strip() if isinstance(schema, str) and schema.strip() else None
    return normalized_schema is None


@dataclasses.dataclass
class HogQLQueryExecutor:
    query: Union[str, ast.SelectQuery, ast.SelectSetQuery] | None
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
    clickhouse_context: Optional[HogQLContext] = None
    clickhouse_sql: Optional[str] = None
    direct_postgres_context: Optional[HogQLContext] = None
    direct_postgres_sql: Optional[str] = None
    direct_postgres_source_id: Optional[str] = None
    direct_postgres_values: dict[str, object] | None = None
    connection_id: Optional[str] = None
    send_raw_query: bool = False
    user: Optional[User] = None

    __uninitialized_context: ClassVar[HogQLContext] = HogQLContext()

    @dataclasses.dataclass(frozen=True)
    class _PreparedExecution:
        sql: str
        context: HogQLContext
        engine: Literal["clickhouse", "direct_postgres"]

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
        self.hogql: Optional[str] = None
        self.print_columns: list[str] = []
        self.has_more: Optional[bool] = None
        self.limit: Optional[int] = None
        self.offset: Optional[int] = None

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

            if finder.has_filters:
                if "filters" in self.placeholders and self.filters is not None:
                    raise ValueError("Query contains 'filters' both as placeholder and as a query parameter.")
                # Build the database once with the executor's modifiers and cache it on the context
                # so that _generate_hogql reuses it instead of building a second Database.
                # Skip for direct-connection queries, whose database needs a connection_id resolved later.
                if self.context.database is None and self.connection_id is None:
                    self.context.database = Database.create_for(
                        team=self.team,
                        user=self.user,
                        modifiers=self.query_modifiers,
                        timings=self.timings,
                    )
                self.select_query = replace_filters(
                    self.select_query, self.filters, self.team, database=self.context.database
                )

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
                assert self.hogql_context.team is not None
                from products.analytics_platform.backend.lazy_computation.lazy_computation_transformer import (
                    Transformer as DailyUniquePersonsPageviewsTransformer,
                )

                transformer = DailyUniquePersonsPageviewsTransformer(self.hogql_context)
                transformed_node = transformer.visit(self.select_query)
                if isinstance(transformed_node, ast.SelectQuery) or isinstance(transformed_node, ast.SelectSetQuery):
                    self.select_query = transformed_node

    @tracer.start_as_current_span("HogQLQueryExecutor._generate_hogql")
    def _generate_hogql(self):
        source = get_direct_connection_source_none_or_raise(
            self.team,
            self.connection_id,
            error_factory=ExposedHogQLError,
        )
        self.connection_id = str(source.id) if source else None

        database = self.context.database
        if database is None or self.connection_id is not None:
            database = Database.create_for(
                team=self.team,
                user=self.user,
                modifiers=self.query_modifiers,
                timings=self.timings,
                connection_id=self.connection_id,
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
                ast.SelectQuery | ast.SelectSetQuery,
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
                    stack = [select_query_hogql] if isinstance(select_query_hogql, ast.SelectQuery) else None
                    self.print_columns.append(
                        print_prepared_ast(
                            node=node,
                            context=self.hogql_context,
                            dialect="hogql",
                            stack=stack,
                        )
                    )

    def _effective_direct_postgres_settings(self) -> HogQLGlobalSettings:
        settings = get_default_hogql_global_settings(
            self.team.pk,
            self.settings,
        )

        if self.limit_context in (
            LimitContext.EXPORT,
            LimitContext.COHORT_CALCULATION,
            LimitContext.QUERY_ASYNC,
            LimitContext.SAVED_QUERY,
            LimitContext.RETENTION,
            LimitContext.POSTHOG_AI,
        ):
            settings.max_execution_time = max(settings.max_execution_time or 0, HOGQL_INCREASED_MAX_EXECUTION_TIME)

        return settings

    def _prepare_direct_postgres_query(self) -> _PreparedExecution | None:
        try:
            query_type = self._get_select_query_type()
        except (QueryError, ResolutionError, AttributeError):
            if self.connection_id is None:
                return None
            raise

        if query_type is None:
            return None

        base_table_types = extract_base_table_types(query_type)
        direct_source_ids = {
            table_type.table.external_data_source_id
            for table_type in base_table_types
            if isinstance(table_type.table, DirectPostgresTable)
        }

        direct_source_id: str | None = None

        if len(direct_source_ids) == 0:
            if self.connection_id is None:
                return None

            if len(base_table_types) > 0:
                raise ExposedHogQLError("Table not found in the selected connection.")

            direct_source_id = self.connection_id

        if len(direct_source_ids) > 1:
            raise ExposedHogQLError("Direct Postgres queries can only reference a single source.")

        has_non_direct_tables = any(
            not isinstance(table_type.table, DirectPostgresTable) for table_type in base_table_types
        )
        if has_non_direct_tables:
            if self.connection_id is None:
                return None
            raise ExposedHogQLError("Direct Postgres queries cannot be joined with PostHog or warehouse-synced tables.")

        if self.connection_id is None:
            raise ExposedHogQLError("Direct Postgres queries require selecting a connection.")

        if direct_source_id is None:
            direct_source_id = next(iter(direct_source_ids))

        if self.connection_id != direct_source_id:
            raise ExposedHogQLError("The query references a different source than the selected connection.")

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
        self.direct_postgres_context = direct_context
        self.direct_postgres_values = direct_context.values
        self.direct_postgres_source_id = direct_source_id

        return self._PreparedExecution(
            sql=self.direct_postgres_sql,
            context=direct_context,
            engine="direct_postgres",
        )

    def _get_select_query_type(self) -> ast.SelectQueryType | ast.SelectSetQueryType | None:
        if self.select_query.type is not None:
            return self.select_query.type

        resolved_query = Resolver(context=self.hogql_context or self.context, dialect="hogql").visit(
            clone_expr(self.select_query, True)
        )

        if isinstance(resolved_query, ast.SelectQuery) or isinstance(resolved_query, ast.SelectSetQuery):
            return resolved_query.type

        return None

    @tracer.start_as_current_span("HogQLQueryExecutor._execute_direct_postgres_query")
    def _execute_direct_postgres_query(self) -> None:
        assert self.direct_postgres_sql is not None
        assert self.direct_postgres_source_id is not None

        from posthog.temporal.data_imports.sources.postgres.postgres import _get_sslmode, source_requires_ssl

        from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

        try:
            source = ExternalDataSource.objects.get(team=self.team, id=self.direct_postgres_source_id)
        except ExternalDataSource.DoesNotExist as e:
            raise ExposedHogQLError("Connection not found or has been deleted") from e

        postgres_source, source_config = validate_direct_postgres_source_config(source, self.team)
        source_schema = source_config.schema
        require_ssl = source_requires_ssl(source, source_config)
        settings = self._effective_direct_postgres_settings()
        statement_timeout_ms = (
            max(settings.max_execution_time or DIRECT_POSTGRES_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1) * 1000
        )

        span = trace.get_current_span()
        span.set_attribute("team_id", self.team.pk)
        span.set_attribute("query_type", self.query_type)
        span.set_attribute("source_id", self.direct_postgres_source_id)

        try:
            with self.timings.measure("postgres_execute"):
                with postgres_source.with_ssh_tunnel(source_config) as (host, port):
                    connection_kwargs: PostgresConnectionKwargs = {
                        "host": host,
                        "port": port,
                        "dbname": source_config.database,
                        "user": source_config.user,
                        "password": source_config.password,
                        "connect_timeout": DIRECT_POSTGRES_CONNECT_TIMEOUT_SECONDS,
                        "sslmode": _get_sslmode(require_ssl),
                        "options": f"-c default_transaction_read_only=on -c statement_timeout={statement_timeout_ms}",
                        # Prevent libpq from probing ~/.postgresql/ for client certs,
                        # which fails with "Permission denied" in containers where
                        # $HOME is /root/ but the process runs as a non-root user.
                        "sslcert": "/tmp/no.txt",
                        "sslkey": "/tmp/no.txt",
                        "sslrootcert": "/tmp/no.txt",
                    }
                    if host.endswith(".us.postwh.com"):
                        # DuckLake hosts require SSL but do not use certificate-based auth.
                        connection_kwargs["sslmode"] = "require"

                    with psycopg.connect(**connection_kwargs) as connection:
                        runtime_connection_metadata = source.connection_metadata
                        if should_hydrate_runtime_direct_postgres_connection_metadata(
                            source_schema,
                            runtime_connection_metadata,
                        ):
                            runtime_connection_metadata = get_runtime_direct_postgres_connection_metadata(
                                connection,
                                runtime_connection_metadata,
                            )
                        session_setup_sql = direct_postgres_session_setup_sql(
                            source_schema,
                            runtime_connection_metadata,
                            host,
                        )
                        if session_setup_sql:
                            connection.execute(session_setup_sql)
                        connection.adapters.register_loader("date", LenientDirectPostgresDateLoader)
                        with connection.cursor() as cursor:
                            cursor.execute(self.direct_postgres_sql, self.direct_postgres_values or None)
                            results = cursor.fetchall()
                            description = cursor.description or []
        except (psycopg.Error, ExposedHogQLError) as error:
            span.set_attribute("error_type", error.__class__.__name__)
            if self.debug:
                self.results = []
                self.error = postgres_error_to_message(error)
                self.types = []
                return
            raise ExposedHogQLError(postgres_error_to_message(error)) from error

        span.set_attribute("row_count", len(results))
        self.results = results
        self.types = [
            (column.name, postgres_oid_to_clickhouse_type(getattr(column, "type_code", None))) for column in description
        ]
        if not self.print_columns:
            self.print_columns = [column.name for column in description]

    @tracer.start_as_current_span("HogQLQueryExecutor._generate_clickhouse_sql")
    def _generate_clickhouse_sql(self):
        settings = get_default_hogql_global_settings(self.team.pk, self.settings)
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
                database=self.hogql_context.database if self.hogql_context else None,
            )
            with self.timings.measure("prepare_ast_for_printing"):
                self.clickhouse_prepared_ast = prepare_ast_for_printing(
                    node=self.select_query,
                    context=self.clickhouse_context,
                    dialect="clickhouse",
                    settings=settings,
                )

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

    def _prepare_execution(self) -> _PreparedExecution:
        self._parse_query()
        self._process_variables()
        self._process_placeholders()
        self._apply_limit()
        with self.timings.measure("_generate_hogql"):
            self._generate_hogql()

        direct_execution = self._prepare_direct_postgres_query()
        if direct_execution is not None:
            return direct_execution

        with self.timings.measure("_generate_clickhouse_sql"):
            self._generate_clickhouse_sql()

        assert self.clickhouse_sql is not None
        assert self.clickhouse_context is not None
        return self._PreparedExecution(
            sql=self.clickhouse_sql,
            context=self.clickhouse_context,
            engine="clickhouse",
        )

    def _execute_raw_direct_postgres_query(self) -> None:
        if not isinstance(self.query, str):
            raise ExposedHogQLError("Sending a raw query requires a raw query string.")

        source = get_direct_connection_source_none_or_raise(
            self.team,
            self.connection_id,
            error_factory=ExposedHogQLError,
        )
        if source is None:
            raise ExposedHogQLError("Sending a raw query requires a valid connection.")
        self.connection_id = str(source.id)
        self.direct_postgres_source_id = self.connection_id
        self.direct_postgres_sql = str(self.query)
        self._execute_direct_postgres_query()

    def _capture_send_raw_query_translation_error(self) -> None:
        """Try a post-success HogQL translation for raw queries.

        On success, this stores the translated HogQL in ``self.hogql`` for the response.
        On failure, it records the exception for telemetry and leaves ``self.hogql`` unset.

        This runs synchronously after the raw query succeeds, so it adds the cost of
        ``_prepare_execution()`` to raw-query responses.
        """
        if not isinstance(self.query, str) or self.connection_id is None:
            return

        try:
            shadow_executor = HogQLQueryExecutor(
                query=str(self.query),
                team=self.team,
                query_type=self.query_type,
                filters=self.filters,
                placeholders=self.placeholders,
                variables=self.variables,
                workload=self.workload,
                settings=self.settings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                pretty=self.pretty,
                connection_id=self.connection_id,
                user=self.user,
            )
            shadow_executor._prepare_execution()
            self.hogql = shadow_executor.hogql
        except Exception as error:
            capture_exception(
                error,
                {
                    "component": "send_raw_query_parse_and_print",
                    "send_raw_query": True,
                    "team_id": self.team.pk,
                    "connection_id": self.connection_id,
                    "query_type": self.query_type,
                },
            )

    @tracer.start_as_current_span("HogQLQueryExecutor._execute_clickhouse_query")
    def _execute_clickhouse_query(self):
        assert self.clickhouse_sql
        clickhouse_context = self.clickhouse_context
        assert clickhouse_context is not None
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

            workload = self.workload
            if workload == Workload.DEFAULT and clickhouse_context.workload is not None:
                workload = clickhouse_context.workload

            try:
                self.results, self.types = sync_execute(
                    self.clickhouse_sql,
                    clickhouse_context.values,
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

        if self.debug and self.error is None:
            with self.timings.measure("explain"):
                # nosemgrep: clickhouse-injection-taint - self.clickhouse_sql is HogQL-compiled from AST, not raw user input; values remain parameterized in clickhouse_context.values
                explain_results = sync_execute(
                    f"EXPLAIN {self.clickhouse_sql}",
                    clickhouse_context.values,
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
                    prepared_ast=self.clickhouse_prepared_ast,
                    printed_sql=self.clickhouse_sql,
                )

    @tracer.start_as_current_span("HogQLQueryExecutor.generate_clickhouse_sql")
    def generate_clickhouse_sql(self) -> tuple[str, HogQLContext]:
        prepared_execution = self._prepare_execution()
        return prepared_execution.sql, prepared_execution.context

    @tracer.start_as_current_span("HogQLQueryExecutor.execute")
    def execute(self) -> HogQLQueryResponse:
        if self.send_raw_query and self.connection_id is not None:
            self._execute_raw_direct_postgres_query()
            self._capture_send_raw_query_translation_error()
        else:
            prepared_execution = self._prepare_execution()

            if prepared_execution.engine == "direct_postgres":
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
            hasMore=self.has_more,
            limit=self.limit,
            offset=self.offset,
        )


def execute_hogql_query(*args, **kwargs) -> HogQLQueryResponse:
    return HogQLQueryExecutor(*args, **kwargs).execute()
