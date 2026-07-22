from typing import TYPE_CHECKING, Any, cast

import sqlparse
from opentelemetry import trace
from sqlparse import tokens as sqlparse_tokens

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_query_metrics import DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL, observe_direct_query
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.capability import is_direct_capable
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError

if TYPE_CHECKING:
    from clickhouse_connect.driver.client import Client as ClickHouseClient

    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.source import ClickHouseSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clickhouse import (
        ClickHouseSourceConfig,
    )

DIRECT_CLICKHOUSE_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
# Hard backstop against loading an unbounded result set into memory — guards a raw passthrough
# `SELECT * FROM huge_table` with no LIMIT (the shared client runs with query_limit=0). HogQL-
# authored queries already carry a LIMIT from the printer.
DIRECT_CLICKHOUSE_MAX_ROWS = 1_000_000
DIRECT_CLICKHOUSE_ROW_CAP_ERROR = (
    f"ClickHouse query returned more than {DIRECT_CLICKHOUSE_MAX_ROWS:,} rows. Add a LIMIT clause."
)
RAW_CLICKHOUSE_READ_ONLY_ERROR = "Raw ClickHouse queries must be read-only SELECT statements."


def clickhouse_error_to_message(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "ClickHouse query failed."
    return message.splitlines()[0]


def ensure_read_only_raw_clickhouse_statement(sql: str) -> str:
    """Enforce read-only for raw ClickHouse SQL.

    ClickHouse has no read-only transaction switch we can set on the connection, so read-only is
    enforced our side (as with Snowflake/Redshift): the statement must be a single ``SELECT`` and
    any DDL — or any DML keyword other than ``SELECT`` anywhere in the statement — is rejected.
    A first-keyword check is not enough: ClickHouse accepts ``WITH 1 AS x INSERT INTO t SELECT x``,
    which starts with ``WITH`` but writes, so the whole statement is inspected. HogQL-authored
    queries only ever emit SELECT. String values and quoted identifiers aren't tagged DML/DDL, so
    a literal or alias like ``'DELETE'`` is unaffected.
    """
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1 or statements[0].get_type() != "SELECT":
        raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)
    for token in statements[0].flatten():
        if token.ttype in sqlparse_tokens.DDL:
            raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)
        if token.ttype in sqlparse_tokens.DML and token.value.upper() != "SELECT":
            raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)
    return sql


def _fetch_capped_clickhouse_rows(
    client: "ClickHouseClient", sql: str, parameters: dict[str, Any] | None
) -> tuple[list, list[str], list[str]]:
    """Stream rows up to the row cap, raising if the result would exceed it.

    The shared client is configured with ``query_limit=0``, so ``client.query`` would buffer the
    full response in the worker process. Streaming row blocks and stopping one row past the cap
    bounds memory to the cap plus a single block, matching the fetchmany(cap+1) guard the
    Snowflake/Redshift adapters use.
    """
    rows: list = []
    with client.query_row_block_stream(sql, parameters=parameters) as stream:
        column_names = list(stream.source.column_names)
        column_types = [str(column_type) for column_type in stream.source.column_types]
        for block in stream:
            rows.extend(block)
            if len(rows) > DIRECT_CLICKHOUSE_MAX_ROWS:
                DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL.labels(dialect="clickhouse").inc()
                raise ExposedHogQLError(DIRECT_CLICKHOUSE_ROW_CAP_ERROR)
    return rows, column_names, column_types


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
            with request.timings.measure("clickhouse_execute"), observe_direct_query("clickhouse"):
                # The SSH tunnel (if any) is opened for the life of the query; the native driver
                # connects to the external ClickHouse directly, never through PostHog's cluster.
                with clickhouse_source.direct_query_client(
                    config,
                    request.team.pk,
                    query_timeout=statement_timeout_seconds,
                    # A server-side execution cap on top of the socket timeout. `max_execution_time`
                    # is a standard setting managed servers accept (unlike a readonly override).
                    settings={"max_execution_time": statement_timeout_seconds},
                ) as client:
                    rows, column_names, column_types = _fetch_capped_clickhouse_rows(
                        client, request.sql, request.values or None
                    )
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
