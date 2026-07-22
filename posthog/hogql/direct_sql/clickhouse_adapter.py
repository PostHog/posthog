from collections.abc import Iterator
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

import sqlparse
from opentelemetry import trace
from sqlparse import tokens as sqlparse_tokens
from sqlparse.sql import Function, TokenList

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
DIRECT_CLICKHOUSE_TIMEOUT_ERROR = "ClickHouse query exceeded the execution time limit."
RAW_CLICKHOUSE_READ_ONLY_ERROR = "Raw ClickHouse queries must be read-only SELECT statements."
RAW_CLICKHOUSE_BLOCKED_FUNCTION_ERROR = "This ClickHouse table function is not allowed in direct queries."

# Table functions that read over the network, from the local filesystem, or spawn a process.
# They parse as a plain SELECT (`SELECT * FROM url(...)`), so the read-only DML/DDL gate doesn't
# stop them — a raw query could otherwise reach the connected server's metadata endpoint (SSRF),
# federate in data from other databases the server can see, or read local files / run programs.
# HogQL-authored queries never emit these; only the raw passthrough path can, so block them by
# name there. Matched case-insensitively and only when the name is a function call (a column
# literally named e.g. `url` tokenizes as an identifier, not a Function, so it's unaffected).
_RAW_CLICKHOUSE_BLOCKED_TABLE_FUNCTIONS = frozenset(
    {
        "URL",
        "URLCLUSTER",
        "S3",
        "S3CLUSTER",
        "GCS",
        "REMOTE",
        "REMOTESECURE",
        "CLUSTER",
        "CLUSTERALLREPLICAS",
        "MYSQL",
        "POSTGRESQL",
        "MONGODB",
        "REDIS",
        "SQLITE",
        "JDBC",
        "ODBC",
        "HDFS",
        "HDFSCLUSTER",
        "FILE",
        "INPUT",
        "AZUREBLOBSTORAGE",
        "AZUREBLOBSTORAGECLUSTER",
        "DELTALAKE",
        "HUDI",
        "ICEBERG",
        "EXECUTABLE",
    }
)


def clickhouse_error_to_message(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "ClickHouse query failed."
    return message.splitlines()[0]


def _iter_function_names(token: TokenList) -> "Iterator[str]":
    """Yield the name of every function call in the statement, recursing into groups.

    Table functions in a FROM clause (``url(...)``, ``s3(...)``) and scalar calls both parse as
    ``sqlparse.sql.Function``; a bare identifier of the same spelling (``SELECT url``) does not.
    """
    for child in token.tokens:
        if isinstance(child, Function):
            name = child.get_name()
            if name:
                yield name
        if child.is_group:
            yield from _iter_function_names(child)


def ensure_read_only_raw_clickhouse_statement(sql: str) -> str:
    """Enforce read-only for raw ClickHouse SQL.

    ClickHouse has no read-only transaction switch we can set on the connection, so read-only is
    enforced our side (as with Snowflake/Redshift): the statement must be a single ``SELECT`` and
    any DDL — or any DML keyword other than ``SELECT`` anywhere in the statement — is rejected.
    A first-keyword check is not enough: ClickHouse accepts ``WITH 1 AS x INSERT INTO t SELECT x``,
    which starts with ``WITH`` but writes, so the whole statement is inspected. Network/file/exec
    table functions (``url``, ``s3``, ``remote``, ``file``, …) are rejected too: they run from a
    plain SELECT and would otherwise let a raw query reach the connected server's metadata endpoint
    (SSRF), read local files, or federate in other databases. HogQL-authored queries only ever emit
    a plain SELECT over the source's own tables. String values and quoted identifiers aren't tagged
    DML/DDL and a same-named column isn't a function call, so a literal, alias, or column like
    ``'DELETE'`` / ``url`` is unaffected.
    """
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1 or statements[0].get_type() != "SELECT":
        raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)
    statement = statements[0]
    for token in statement.flatten():
        if token.ttype in sqlparse_tokens.DDL:
            raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)
        if token.ttype in sqlparse_tokens.DML and token.value.upper() != "SELECT":
            raise ExposedHogQLError(RAW_CLICKHOUSE_READ_ONLY_ERROR)
    for function_name in _iter_function_names(statement):
        if function_name.upper() in _RAW_CLICKHOUSE_BLOCKED_TABLE_FUNCTIONS:
            raise ExposedHogQLError(RAW_CLICKHOUSE_BLOCKED_FUNCTION_ERROR)
    return sql


def _fetch_capped_clickhouse_rows(
    client: "ClickHouseClient", sql: str, parameters: dict[str, Any] | None, deadline_seconds: float
) -> tuple[list, list[str], list[str]]:
    """Stream rows up to the row cap, raising if the result would exceed it or the deadline passes.

    The shared client is configured with ``query_limit=0``, so ``client.query`` would buffer the
    full response in the worker process. Streaming row blocks and stopping one row past the cap
    bounds memory to the cap plus a single block, matching the fetchmany(cap+1) guard the
    Snowflake/Redshift adapters use.

    The per-block wall-clock deadline is the real timeout backstop: a raw query can override the
    server-side ``max_execution_time`` with its own ``SETTINGS`` clause, and dribbling rows out in
    tiny blocks keeps the socket read-timeout from ever firing — so a slow query would otherwise
    pin the worker and SSH tunnel indefinitely. Bailing once ``deadline_seconds`` elapses (and
    closing the client, which drops the connection so ClickHouse cancels the query) enforces the
    cap regardless of any in-query setting.
    """
    rows: list = []
    started = perf_counter()
    with client.query_row_block_stream(sql, parameters=parameters) as stream:
        column_names = list(stream.source.column_names)
        column_types = [str(column_type) for column_type in stream.source.column_types]
        for block in stream:
            if perf_counter() - started > deadline_seconds:
                raise ExposedHogQLError(DIRECT_CLICKHOUSE_TIMEOUT_ERROR)
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
                        client, request.sql, request.values or None, statement_timeout_seconds
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
