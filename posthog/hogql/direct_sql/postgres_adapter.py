from contextlib import ExitStack
from typing import TYPE_CHECKING, TypedDict, cast

import psycopg
from opentelemetry import trace
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult, parse_direct_source_config
from posthog.hogql.direct_sql.capability import is_direct_capable
from posthog.hogql.direct_sql.pgwire import (
    MANAGED_WAREHOUSE_CONNECTION_ERROR,
    LenientDirectPostgresDateLoader,
    postgres_error_to_message,
    postgres_oid_to_clickhouse_type,
)
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.escape_sql import escape_postgres_identifier
from posthog.hogql.timings import HogQLTimings

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
        PostgresSourceConfig,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

DIRECT_POSTGRES_CONNECT_TIMEOUT_SECONDS = 15
DIRECT_POSTGRES_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600


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


def is_postwh_host(host: str | None) -> bool:
    # Hostnames are case-insensitive and may carry a trailing root-zone dot, so
    # normalize before matching to keep the sslmode enforcement bypass-proof.
    if host is None:
        return False
    return host.lower().rstrip(".").endswith(".postwh.com")


def direct_postgres_session_setup_sql(
    schema: str | None,
    connection_metadata: dict[str, object] | None = None,
    host: str | None = None,
) -> str | None:
    engine = connection_metadata.get("engine") if isinstance(connection_metadata, dict) else None
    database = connection_metadata.get("database") if isinstance(connection_metadata, dict) else None
    normalized_schema = schema.strip() if isinstance(schema, str) and schema.strip() else None

    if engine == "duckdb" or is_postwh_host(host):
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


class PostgresAdapter:
    engine = "postgres"
    dialect: HogQLDialect | None = "postgres"

    def validate_source_config(
        self, source: "ExternalDataSource", team: "Team", timings: HogQLTimings | None = None
    ) -> tuple["PostgresSource", "PostgresSourceConfig"]:
        timings = timings or HogQLTimings()
        with timings.measure("postgres_source_config"):
            with timings.measure("postgres_source_capability"):
                # Capability, not access_method: a synced source with the direct-query toggle on is valid too.
                if not (is_direct_capable(source) and source.direct_engine == self.engine):
                    raise ExposedHogQLError("Invalid direct Postgres connection.")

            with timings.measure("postgres_source_registry", emit_span=True):
                from products.warehouse_sources.backend.facade.source_management import PostgresSource, SourceRegistry
                from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

                postgres_source = cast(PostgresSource, SourceRegistry.get_source(ExternalDataSourceType.POSTGRES))
            with timings.measure("postgres_source_parse_config"):
                config = parse_direct_source_config(postgres_source, source)

        with timings.measure("postgres_ssh_validation"):
            is_ssh_valid, ssh_valid_errors = postgres_source.ssh_tunnel_is_valid(config, team.pk)
            if not is_ssh_valid:
                raise ExposedHogQLError(ssh_valid_errors or "Invalid SSH tunnel configuration.")

        with timings.measure("postgres_host_validation"):
            valid_host, host_errors = postgres_source.is_database_host_valid(
                config.host, team.pk, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
            )
            if not valid_host:
                raise ExposedHogQLError(host_errors or "Invalid Postgres host.")

        return postgres_source, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_single_direct_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        source = request.source
        with request.timings.measure("postgres_source_validation"):
            with request.timings.measure("postgres_source_helpers_import"):
                from products.warehouse_sources.backend.facade.source_management import (
                    _get_sslmode,
                    source_requires_ssl,
                )

            postgres_source, source_config = self.validate_source_config(source, request.team, request.timings)
            source_schema = source_config.schema
            require_ssl = source_requires_ssl(source, source_config)
        settings = request.settings
        statement_timeout_ms = (
            max(settings.max_execution_time or DIRECT_POSTGRES_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1) * 1000
        )

        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(source.id))

        try:
            with request.timings.measure("postgres_execute"):
                with ExitStack() as tunnel_stack:
                    with request.timings.measure("postgres_tunnel_open", emit_span=True):
                        host, port = tunnel_stack.enter_context(postgres_source.with_ssh_tunnel(source_config))
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
                    if is_postwh_host(host):
                        # DuckLake hosts (any region: .us/.eu/.dev.postwh.com) require SSL
                        # but do not use certificate-based auth.
                        connection_kwargs["sslmode"] = "require"

                    with request.timings.measure("postgres_connect", emit_span=True):
                        try:
                            connection_context = psycopg.connect(**connection_kwargs)
                        except (psycopg.Error, RuntimeError, ValueError) as error:
                            if source.is_managed_warehouse_ready:
                                raise ExposedHogQLError(MANAGED_WAREHOUSE_CONNECTION_ERROR) from error
                            raise
                    with connection_context as connection:
                        runtime_connection_metadata = source.connection_metadata
                        if should_hydrate_runtime_direct_postgres_connection_metadata(
                            source_schema,
                            runtime_connection_metadata,
                        ):
                            with request.timings.measure("postgres_connection_metadata"):
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
                            with request.timings.measure("postgres_session_setup"):
                                connection.execute(session_setup_sql)
                        connection.adapters.register_loader("date", LenientDirectPostgresDateLoader)
                        with connection.cursor() as cursor:
                            with request.timings.measure("postgres_query_execute"):
                                cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute
                                    request.sql, request.values or None
                                )
                            # Statements that don't produce a result set (e.g. ATTACH, SET, other
                            # DDL/utility commands) leave cursor.description as None; calling
                            # fetchall() on them raises ProgrammingError. Treat them as a
                            # successful, empty result instead of surfacing a spurious error.
                            description = cursor.description or []
                            with request.timings.measure("postgres_query_fetch"):
                                results = cursor.fetchall() if description else []
        except (psycopg.Error, BaseSSHTunnelForwarderError, ExposedHogQLError) as error:
            span.set_attribute("error_type", error.__class__.__name__)
            if request.debug:
                return DirectQueryResult(results=[], types=[], print_columns=[], error=postgres_error_to_message(error))
            raise ExposedHogQLError(postgres_error_to_message(error)) from error

        span.set_attribute("row_count", len(results))
        types: list[tuple[str, str]] = [
            (column.name, postgres_oid_to_clickhouse_type(getattr(column, "type_code", None))) for column in description
        ]
        print_columns = [column.name for column in description]
        return DirectQueryResult(results=results, types=types, print_columns=print_columns)
