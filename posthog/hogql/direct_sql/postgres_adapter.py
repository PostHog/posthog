from datetime import date, datetime
from typing import TYPE_CHECKING, TypedDict, cast

import psycopg
from opentelemetry import trace
from psycopg.types.datetime import DateLoader

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.escape_sql import escape_postgres_identifier

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
    from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

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


class PostgresAdapter:
    engine = "postgres"
    dialect: HogQLDialect | None = "postgres"

    def validate_source_config(
        self, source: "ExternalDataSource", team: "Team"
    ) -> tuple["PostgresSource", "PostgresSourceConfig"]:
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
        from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        if not source.is_direct_postgres:
            raise ExposedHogQLError("Invalid direct Postgres connection.")

        postgres_source = cast(PostgresSource, SourceRegistry.get_source(ExternalDataSourceType.POSTGRES))
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

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_single_direct_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
            _get_sslmode,
            source_requires_ssl,
        )

        source = request.source
        postgres_source, source_config = self.validate_source_config(source, request.team)
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
                            cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute
                                request.sql, request.values or None
                            )
                            # Statements that don't produce a result set (e.g. ATTACH, SET, other
                            # DDL/utility commands) leave cursor.description as None; calling
                            # fetchall() on them raises ProgrammingError. Treat them as a
                            # successful, empty result instead of surfacing a spurious error.
                            description = cursor.description or []
                            results = cursor.fetchall() if description else []
        except (psycopg.Error, ExposedHogQLError) as error:
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
