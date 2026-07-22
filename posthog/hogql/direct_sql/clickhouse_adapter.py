from typing import TYPE_CHECKING, cast

import sqlparse
from opentelemetry import trace
from sqlparse import tokens as sqlparse_tokens

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.capability import is_direct_capable
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.source import ClickHouseSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
        ClickHouseSourceConfig,
    )

DIRECT_CLICKHOUSE_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
RAW_CLICKHOUSE_READ_ONLY_ERROR = "Raw ClickHouse queries must be read-only SELECT statements."


def clickhouse_error_to_message(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "ClickHouse query failed."
    return message.splitlines()[0]


def ensure_read_only_raw_clickhouse_statement(sql: str) -> str:
    """Allow a single read-only statement — one whose first significant keyword is SELECT or WITH.
    ClickHouse writes (INSERT/ALTER/CREATE/DROP/RENAME/TRUNCATE/OPTIMIZE/SYSTEM/SET/…) all start with a
    different keyword, so a first-keyword check is a robust read-only guard for raw queries."""
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1:
        raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)
    for token in statements[0].flatten():
        if token.is_whitespace or token.ttype in sqlparse_tokens.Comment:
            continue
        value = token.value.upper()
        if token.ttype in sqlparse_tokens.Keyword and value in ("SELECT", "WITH"):
            return sql
        # First significant token is anything else (a write keyword, or an identifier) → reject.
        raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)
    raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)


class ClickHouseAdapter:
    engine = "clickhouse"
    dialect: HogQLDialect | None = "clickhouse"

    def validate_source_config(
        self, source: "ExternalDataSource", team: "Team"
    ) -> tuple["ClickHouseSource", "ClickHouseSourceConfig"]:
        from products.warehouse_sources.backend.facade.source_management import SourceRegistry
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

        # Capability, not access_method: a synced source with the direct-query toggle on is valid too.
        if not (is_direct_capable(source) and source.direct_engine == self.engine):
            raise ExposedHogQLError("Invalid direct ClickHouse connection.")

        source_type = (
            ExternalDataSourceType.CLICKHOUSECLOUD
            if source.source_type == ExternalDataSourceType.CLICKHOUSECLOUD
            else ExternalDataSourceType.CLICKHOUSE
        )
        clickhouse_source = cast("ClickHouseSource", SourceRegistry.get_source(source_type))
        config = clickhouse_source.parse_config(source.job_inputs or {})

        is_ssh_valid, ssh_valid_errors = clickhouse_source.ssh_tunnel_is_valid(config, team.pk)
        if not is_ssh_valid:
            raise ExposedHogQLError(ssh_valid_errors or "Invalid SSH tunnel configuration.")

        valid_host, host_errors = clickhouse_source.is_database_host_valid(
            config.host, team.pk, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
        )
        if not valid_host:
            raise ExposedHogQLError(host_errors or "Invalid ClickHouse host.")

        return clickhouse_source, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_clickhouse_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        from clickhouse_connect.driver.exceptions import ClickHouseError

        from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.clickhouse import _get_client

        source = request.source
        clickhouse_source, config = self.validate_source_config(source, request.team)
        settings = request.settings
        statement_timeout_seconds = max(
            settings.max_execution_time or DIRECT_CLICKHOUSE_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1
        )

        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(source.id))

        try:
            with request.timings.measure("clickhouse_execute"):
                # The SSH tunnel (if any) is opened for the life of the query; the native driver
                # connects to the external ClickHouse directly, never through PostHog's cluster.
                with clickhouse_source.with_ssh_tunnel(config, request.team.pk) as (host, port):
                    client = _get_client(
                        host=host,
                        port=port,
                        database=config.database,
                        user=config.user,
                        password=config.password,
                        secure=config.secure,
                        verify=config.verify,
                        query_timeout=statement_timeout_seconds,
                        # A server-side execution cap on top of the socket timeout. `max_execution_time`
                        # is a standard setting managed servers accept (unlike a readonly override).
                        settings={"max_execution_time": statement_timeout_seconds},
                    )
                    try:
                        result = client.query(request.sql, parameters=request.values or None)
                        rows = result.result_rows
                        column_names = list(result.column_names)
                        column_types = [str(column_type) for column_type in result.column_types]
                    finally:
                        client.close()
        except (ClickHouseError, OSError, ExposedHogQLError) as error:
            span.set_attribute("error_type", error.__class__.__name__)
            if request.debug:
                return DirectQueryResult(
                    results=[], types=[], print_columns=[], error=clickhouse_error_to_message(error)
                )
            raise ExposedHogQLError(clickhouse_error_to_message(error)) from error

        span.set_attribute("row_count", len(rows))
        types: list[tuple[str, str]] = list(zip(column_names, column_types))
        return DirectQueryResult(results=[list(row) for row in rows], types=types, print_columns=column_names)
