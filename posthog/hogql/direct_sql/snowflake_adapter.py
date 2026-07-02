import re
from typing import TYPE_CHECKING, cast

import sqlparse
import snowflake.connector
from opentelemetry import trace
from snowflake.connector.constants import FIELD_ID_TO_NAME
from sqlparse import tokens as sqlparse_tokens

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_query_metrics import DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL, observe_direct_query
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.snowflake_connection_cache import cached_snowflake_connection

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig
    from products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.snowflake import (
        SnowflakeImplementation,
    )

DIRECT_SNOWFLAKE_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
# Hard backstop against loading an unbounded result set into memory. Snowflake has no
# read-only transaction mode, so this guards a raw passthrough `SELECT * FROM huge_table`
# with no LIMIT. HogQL-authored queries already carry a LIMIT from the printer.
DIRECT_SNOWFLAKE_MAX_ROWS = 1_000_000
RAW_SNOWFLAKE_READ_ONLY_ERROR = "Raw Snowflake queries must be read-only SELECT statements."
RAW_SNOWFLAKE_BLOCKED_FUNCTION_ERROR = "This Snowflake function is not allowed in direct queries."

# Functions that parse as a plain SELECT but breach the read-only / session-isolation boundary,
# so the single-SELECT gate alone isn't enough. SYSTEM$* are admin / side-effecting (e.g.
# SYSTEM$CANCEL_QUERY); RESULT_SCAN + LAST_QUERY_ID can read another request's result set off a
# reused session. HogQL-authored SQL never emits these — only the raw passthrough path can — so
# block them there. Quoted identifiers tokenize as strings, not names, so a column legitimately
# named e.g. "result_scan" is unaffected.
_RAW_SNOWFLAKE_BLOCKED_FUNCTIONS = frozenset({"RESULT_SCAN", "LAST_QUERY_ID"})
DIRECT_SNOWFLAKE_ROW_CAP_ERROR = (
    f"Snowflake query returned more than {DIRECT_SNOWFLAKE_MAX_ROWS:,} rows. Add a LIMIT clause."
)

# A Snowflake account identifier is either the org-account form (`orgname-account_name`)
# or the legacy dotted form (`account.region.cloud`) — letters, digits, hyphens, underscores,
# and dots only. Rejecting anything else keeps a crafted value from steering the connector at
# an arbitrary host (the account is interpolated into the host it dials), closing the SSRF gap
# that host validation covers for the Postgres and MySQL adapters.
_SNOWFLAKE_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Snowflake's Python connector reports column types as integer codes in
# cursor.description[*].type_code, decoded to names via FIELD_ID_TO_NAME. Those names are
# Snowflake's *internal* vocabulary (FIXED/REAL/TEXT/…), not SQL type names — e.g.
# NUMBER/DECIMAL/INT all surface as FIXED, VARCHAR/CHAR as TEXT. FIXED is resolved separately
# (scale decides int vs decimal), so it's not here.
SNOWFLAKE_FIELD_NAME_TO_CLICKHOUSE_TYPE: dict[str, str] = {
    "REAL": "Float64",
    "TEXT": "String",
    "BOOLEAN": "Bool",
    "DATE": "Date",
    "TIME": "String",
    "TIMESTAMP": "DateTime64(6, 'UTC')",
    "TIMESTAMP_NTZ": "DateTime64(6, 'UTC')",
    "TIMESTAMP_LTZ": "DateTime64(6, 'UTC')",
    "TIMESTAMP_TZ": "DateTime64(6, 'UTC')",
    "VARIANT": "String",
    "OBJECT": "String",
    "ARRAY": "String",
    "MAP": "String",
    "BINARY": "String",
    "GEOGRAPHY": "String",
    "GEOMETRY": "String",
    "VECTOR": "String",
}


def snowflake_field_type_to_clickhouse_type(type_code: object | None, scale: object | None = None) -> str:
    # type_code is the integer index into Snowflake's FIELD_ID_TO_NAME, taken from
    # cursor.description; a str(type_code) lookup never matches a name and silently types
    # every column as String.
    if not isinstance(type_code, int):
        return "String"
    name = FIELD_ID_TO_NAME.get(type_code, "")
    if name == "FIXED":
        # NUMBER/DECIMAL/INT all report as FIXED; scale 0 (or absent) is an integer.
        return "Decimal" if isinstance(scale, int) and scale > 0 else "Int64"
    return SNOWFLAKE_FIELD_NAME_TO_CLICKHOUSE_TYPE.get(name, "String")


def snowflake_error_to_message(error: Exception) -> str:
    if isinstance(error, snowflake.connector.errors.Error):
        args = error.args
        if len(args) >= 2 and isinstance(args[1], str) and args[1].strip():
            return args[1].strip().splitlines()[0]
    message = str(error).strip()
    if not message:
        return "Snowflake query failed."
    return message.splitlines()[0]


def validate_snowflake_account_id(account_id: str | None) -> str:
    candidate = (account_id or "").strip()
    if not candidate or not _SNOWFLAKE_ACCOUNT_ID_RE.fullmatch(candidate):
        raise ExposedHogQLError("Invalid Snowflake account identifier.")
    return candidate


def ensure_read_only_raw_snowflake_statement(sql: str) -> str:
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1 or statements[0].get_type() != "SELECT":
        raise ExposedHogQLError(RAW_SNOWFLAKE_READ_ONLY_ERROR)
    # Snowflake has no read-only session/transaction switch — the Postgres path sets
    # default_transaction_read_only on the connection, but Snowflake offers no equivalent. So
    # this single-read-only-SELECT gate is the enforcement boundary (backed at runtime by the
    # MULTI_STATEMENT_COUNT=1 session pin). As defense in depth, reject any DDL, or any DML
    # keyword other than SELECT, appearing anywhere in the statement — e.g. a write smuggled
    # into a subquery. String values and quoted identifiers aren't tagged DML/DDL, so a literal
    # or alias like 'DELETE' is unaffected.
    for token in statements[0].flatten():
        if token.ttype in sqlparse_tokens.DDL:
            raise ExposedHogQLError(RAW_SNOWFLAKE_READ_ONLY_ERROR)
        if token.ttype in sqlparse_tokens.DML and token.value.upper() != "SELECT":
            raise ExposedHogQLError(RAW_SNOWFLAKE_READ_ONLY_ERROR)
        if token.ttype in sqlparse_tokens.Name:
            name = token.value.upper()
            if name.startswith("SYSTEM$") or name in _RAW_SNOWFLAKE_BLOCKED_FUNCTIONS:
                raise ExposedHogQLError(RAW_SNOWFLAKE_BLOCKED_FUNCTION_ERROR)
    return sql


def _fetch_capped_snowflake_rows(cursor: snowflake.connector.cursor.SnowflakeCursor) -> list:
    """Fetch up to the row cap, raising if the result would exceed it.

    Reads one row past the cap so the limit can be enforced without materializing the entire
    result set first.
    """
    rows = cursor.fetchmany(DIRECT_SNOWFLAKE_MAX_ROWS + 1)
    if len(rows) > DIRECT_SNOWFLAKE_MAX_ROWS:
        DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL.labels(dialect="snowflake").inc()
        raise ExposedHogQLError(DIRECT_SNOWFLAKE_ROW_CAP_ERROR)
    return list(rows)


class SnowflakeAdapter:
    engine = "snowflake"
    dialect: HogQLDialect | None = "snowflake"

    def validate_source_config(
        self, source: "ExternalDataSource", team: "Team"
    ) -> tuple["SnowflakeImplementation", "SnowflakeSourceConfig"]:
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
        from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
        from products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.source import SnowflakeSource

        if not source.is_direct_snowflake:
            raise ExposedHogQLError("Invalid direct Snowflake connection.")

        snowflake_source = cast(SnowflakeSource, SourceRegistry.get_source(ExternalDataSourceType.SNOWFLAKE))
        config = snowflake_source.parse_config(source.job_inputs or {})

        # Snowflake has no host/SSH-tunnel config to validate (the Postgres/MySQL SSRF check),
        # but the account identifier flows into the host the connector dials, so it gets the
        # same scrutiny.
        validate_snowflake_account_id(config.account_id)

        return snowflake_source.get_implementation, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_snowflake_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        """Execute a single read-only statement against the source's Snowflake account.

        Snowflake has no read-only session/transaction switch (the Postgres path sets
        default_transaction_read_only on the connection; there is no equivalent), so read-only
        is enforced our side: the statement is rejected unless it is a single read-only SELECT
        (`prepare_raw_sql`), HogQL-authored queries only ever emit SELECT, and the session pins
        MULTI_STATEMENT_COUNT=1 so the server refuses any stacked statement. A least-privilege
        SELECT-only role is recommended as defense in depth, but is not the boundary we rely on.
        """
        source = request.source
        snowflake_implementation, source_config = self.validate_source_config(source, request.team)
        settings = request.settings
        statement_timeout_seconds = max(
            settings.max_execution_time or DIRECT_SNOWFLAKE_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1
        )

        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(source.id))

        try:
            with request.timings.measure("snowflake_execute"), observe_direct_query("snowflake"):
                # Reuse a per-thread connection across queries — the auth handshake is the
                # dominant cost for interactive use.
                with cached_snowflake_connection(snowflake_implementation, source_config) as connection:
                    with connection.cursor() as cursor:
                        # Server-side backstop: refuse stacked statements regardless of the
                        # connector default, so the single-statement parse gate can't be bypassed.
                        cursor.execute("ALTER SESSION SET MULTI_STATEMENT_COUNT = 1")
                        cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {statement_timeout_seconds}")
                        cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute
                            request.sql, request.values or None
                        )
                        results = _fetch_capped_snowflake_rows(cursor)
                        description = cursor.description or []
        except (snowflake.connector.errors.Error, ExposedHogQLError) as error:
            span.set_attribute("error_type", error.__class__.__name__)
            if request.debug:
                return DirectQueryResult(
                    results=[], types=[], print_columns=[], error=snowflake_error_to_message(error)
                )
            raise ExposedHogQLError(snowflake_error_to_message(error)) from error

        span.set_attribute("row_count", len(results))
        types: list[tuple[str, str]] = [
            (column[0], snowflake_field_type_to_clickhouse_type(column[1], column[5] if len(column) > 5 else None))
            for column in description
        ]
        print_columns = [column[0] for column in description]
        return DirectQueryResult(results=results, types=types, print_columns=print_columns)
