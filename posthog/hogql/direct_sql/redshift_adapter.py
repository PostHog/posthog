from typing import TYPE_CHECKING, cast

import psycopg
import sqlparse
from opentelemetry import trace
from sqlparse import tokens as sqlparse_tokens

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_query_metrics import observe_direct_query
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.postgres_adapter import postgres_error_to_message, postgres_oid_to_clickhouse_type
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.escape_sql import escape_postgres_identifier

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RedshiftSourceConfig
    from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift import (
        RedshiftImplementation,
    )

DIRECT_REDSHIFT_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
RAW_REDSHIFT_READ_ONLY_ERROR = "Raw Redshift queries must be read-only SELECT statements."


def ensure_read_only_raw_redshift_statement(sql: str) -> str:
    """Enforce read-only for raw Redshift SQL.

    Redshift, unlike Postgres, exposes no read-only transaction switch — its settable server
    parameters don't include ``default_transaction_read_only``. So read-only is enforced our side
    (as with Snowflake): a raw statement must be a single ``SELECT``, and any DDL — or any DML
    keyword other than ``SELECT`` anywhere in the statement (e.g. a write smuggled into a
    subquery) — is rejected. HogQL-authored queries only ever emit SELECT. String values and
    quoted identifiers aren't tagged DML/DDL, so a literal or alias like ``'DELETE'`` is unaffected.
    """
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1 or statements[0].get_type() != "SELECT":
        raise ExposedHogQLError(RAW_REDSHIFT_READ_ONLY_ERROR)
    for token in statements[0].flatten():
        if token.ttype in sqlparse_tokens.DDL:
            raise ExposedHogQLError(RAW_REDSHIFT_READ_ONLY_ERROR)
        if token.ttype in sqlparse_tokens.DML and token.value.upper() != "SELECT":
            raise ExposedHogQLError(RAW_REDSHIFT_READ_ONLY_ERROR)
    return sql


class RedshiftAdapter:
    engine = "redshift"
    dialect: HogQLDialect | None = "redshift"

    def validate_source_config(
        self, source: "ExternalDataSource", team: "Team"
    ) -> tuple["RedshiftImplementation", "RedshiftSourceConfig"]:
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
        from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
        from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source import RedshiftSource

        if not source.is_direct_redshift:
            raise ExposedHogQLError("Invalid direct Redshift connection.")

        redshift_source = cast(RedshiftSource, SourceRegistry.get_source(ExternalDataSourceType.REDSHIFT))
        config = redshift_source.parse_config(source.job_inputs or {})

        is_ssh_valid, ssh_valid_errors = redshift_source.ssh_tunnel_is_valid(config, team.pk)
        if not is_ssh_valid:
            raise ExposedHogQLError(ssh_valid_errors or "Invalid SSH tunnel configuration.")

        valid_host, host_errors = redshift_source.is_database_host_valid(
            config.host, team.pk, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
        )
        if not valid_host:
            raise ExposedHogQLError(host_errors or "Invalid Redshift host.")

        return redshift_source.get_implementation, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_redshift_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        source = request.source
        redshift_implementation, source_config = self.validate_source_config(source, request.team)
        source_schema = source_config.schema
        settings = request.settings
        statement_timeout_ms = (
            max(settings.max_execution_time or DIRECT_REDSHIFT_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1) * 1000
        )

        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(source.id))

        try:
            with request.timings.measure("redshift_execute"), observe_direct_query("redshift"):
                # `connect` opens the SSH tunnel (if any) and applies the shared Redshift SSL
                # conventions in one place.
                with redshift_implementation.connect(source_config) as connection:
                    # statement_timeout is a Redshift-settable parameter (milliseconds). The value is
                    # a validated int, so inlining it is injection-safe.
                    connection.execute(f"SET statement_timeout TO {int(statement_timeout_ms)}")
                    if isinstance(source_schema, str) and source_schema.strip():
                        connection.execute(f"SET search_path TO {escape_postgres_identifier(source_schema.strip())}")
                    with connection.cursor() as cursor:
                        cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute
                            request.sql, request.values or None
                        )
                        # Utility statements (SET, etc.) leave cursor.description as None; treat them
                        # as an empty result instead of raising on fetchall(), mirroring Postgres.
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
