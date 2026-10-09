from __future__ import annotations

from concurrent import futures
from typing import TYPE_CHECKING, cast

import sqlparse
from opentelemetry import trace
from sqlparse import tokens as sqlparse_tokens

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_query_metrics import DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL, observe_direct_query
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult, parse_direct_source_config
from posthog.hogql.direct_sql.capability import bigquery_direct_query_enabled, is_direct_capable
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError

if TYPE_CHECKING:
    from google.cloud import bigquery

    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source import BigQuerySource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigquery import (
        BigQuerySourceConfig,
    )

DIRECT_BIGQUERY_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
# Backstop against loading an unbounded result set into memory: a raw passthrough
# `SELECT * FROM huge_table` carries no LIMIT.
DIRECT_BIGQUERY_MAX_ROWS = 1_000_000
RAW_BIGQUERY_READ_ONLY_ERROR = "Raw BigQuery queries must be read-only SELECT statements."
DIRECT_BIGQUERY_ROW_CAP_ERROR = (
    f"BigQuery query returned more than {DIRECT_BIGQUERY_MAX_ROWS:,} rows. Add a LIMIT clause."
)
DIRECT_BIGQUERY_TIMEOUT_ERROR = "BigQuery query timed out."

# BigQuery reports legacy type names (INTEGER not INT64, BOOLEAN not BOOL). The standard-SQL
# aliases are included so a client library change degrades to the same mapping.
BIGQUERY_FIELD_TYPE_TO_CLICKHOUSE_TYPE: dict[str, str] = {
    "INTEGER": "Int64",
    "INT64": "Int64",
    "FLOAT": "Float64",
    "FLOAT64": "Float64",
    "NUMERIC": "Decimal",
    "BIGNUMERIC": "Decimal",
    "STRING": "String",
    "BOOLEAN": "Bool",
    "BOOL": "Bool",
    "DATE": "Date",
    "DATETIME": "DateTime64(6, 'UTC')",
    "TIMESTAMP": "DateTime64(6, 'UTC')",
    "TIME": "String",
    "BYTES": "String",
    "RECORD": "String",
    "STRUCT": "String",
    "GEOGRAPHY": "String",
    "JSON": "String",
    "INTERVAL": "String",
    "RANGE": "String",
}


def bigquery_field_to_clickhouse_type(field_type: str | None, mode: str | None = None) -> str:
    # A REPEATED field is an array; arrays surface as String, like Snowflake's ARRAY.
    if mode == "REPEATED":
        return "String"
    if not field_type:
        return "String"
    return BIGQUERY_FIELD_TYPE_TO_CLICKHOUSE_TYPE.get(field_type.upper(), "String")


def bigquery_error_to_message(error: Exception) -> str:
    # google.api_core call errors carry the server's message without the "403 GET https://…"
    # prefix str() adds.
    message = getattr(error, "message", None)
    if not isinstance(message, str) or not message.strip():
        message = str(error).strip()
    if not message:
        return "BigQuery query failed."
    return message.splitlines()[0]


def ensure_read_only_raw_bigquery_statement(sql: str) -> str:
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1 or statements[0].get_type() != "SELECT":
        raise ExposedHogQLError(RAW_BIGQUERY_READ_ONLY_ERROR)
    # BigQuery has no read-only session switch, and a single query job will run a
    # multi-statement script, so this gate is the enforcement boundary on our side. The
    # service account's read-only grants (Data Viewer + Job User) are the server-side
    # backstop. The token scan below catches a write smuggled into a subquery. Unlike
    # Snowflake there are no session-scoped functions to blocklist.
    for token in statements[0].flatten():
        if token.ttype in sqlparse_tokens.DDL:
            raise ExposedHogQLError(RAW_BIGQUERY_READ_ONLY_ERROR)
        if token.ttype in sqlparse_tokens.DML and token.value.upper() != "SELECT":
            raise ExposedHogQLError(RAW_BIGQUERY_READ_ONLY_ERROR)
    return sql


def _resolve_query_location(config: BigQuerySourceConfig) -> str | None:
    """The BigQuery location to pin query jobs to, or None to let the server infer it.

    The server infers a job's location from the datasets the query references, so None
    works for ordinary table reads.
    """
    custom_region = config.use_custom_region
    if custom_region is not None and custom_region.enabled and custom_region.region:
        return custom_region.region.strip() or None
    return None


def _fetch_capped_bigquery_rows(row_iterator: bigquery.table.RowIterator) -> list:
    """Collect up to the row cap, raising if the result exceeds it. The iterator is created
    with max_results one past the cap, so the overflow is detectable."""
    rows = [row.values() for row in row_iterator]
    if len(rows) > DIRECT_BIGQUERY_MAX_ROWS:
        DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL.labels(dialect="bigquery").inc()
        raise ExposedHogQLError(DIRECT_BIGQUERY_ROW_CAP_ERROR)
    return rows


class BigQueryAdapter:
    engine = "bigquery"
    # Raw-only: no HogQL printer dialect exists for BigQuery, so only sendRawQuery works.
    dialect: HogQLDialect | None = None

    def validate_source_config(
        self, source: ExternalDataSource, team: Team
    ) -> tuple[BigQuerySource, BigQuerySourceConfig]:
        from products.warehouse_sources.backend.facade.source_management import SourceRegistry
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

        # Capability, not access_method: a synced source with the direct-query toggle on is valid too.
        if not (is_direct_capable(source) and source.direct_engine == self.engine):
            raise ExposedHogQLError("Invalid direct BigQuery connection.")

        # The flag is also checked where connections are created; checking here too makes
        # turning it off stop queries on already-created connections.
        if not bigquery_direct_query_enabled(team):
            raise ExposedHogQLError("BigQuery direct queries are not enabled for this project.")

        bigquery_source = cast("BigQuerySource", SourceRegistry.get_source(ExternalDataSourceType.BIGQUERY))
        config = parse_direct_source_config(bigquery_source, source)

        # No host/SSRF check needed: every request goes to Google's fixed API hosts, and the
        # key file's token_uri is checked against the Google OAuth allowlist when credentials
        # are built.
        return bigquery_source, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_bigquery_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        """Execute a single read-only statement against the source's BigQuery project.

        The job gets a server-side timeout (`job_timeout_ms`) in addition to the client-side
        wait, so an abandoned request doesn't keep billing the customer.
        """
        from google.api_core import exceptions as google_api_exceptions
        from google.auth import exceptions as google_auth_exceptions
        from google.cloud import bigquery

        from products.warehouse_sources.backend.facade.source_management import (
            bigquery_client,
            is_bigquery_auth_error,
            resolve_bigquery_auth,
        )

        source = request.source
        _, source_config = self.validate_source_config(source, request.team)
        if request.values:
            # Only the raw path reaches this adapter, and raw SQL never carries bound parameters.
            raise InternalHogQLError("Direct BigQuery queries do not support bound parameters.")
        statement_timeout_seconds = max(
            request.settings.max_execution_time or DIRECT_BIGQUERY_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1
        )

        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(source.id))

        try:
            with request.timings.measure("bigquery_execute"), observe_direct_query("bigquery"):
                auth = resolve_bigquery_auth(source_config, request.team.pk)
                job_config = bigquery.QueryJobConfig(
                    use_legacy_sql=False,
                    job_timeout_ms=statement_timeout_seconds * 1000,
                )
                with bigquery_client(
                    auth.project_id, _resolve_query_location(source_config), auth.credentials
                ) as client:
                    job = client.query(request.sql, job_config=job_config)
                    row_iterator = job.result(
                        timeout=statement_timeout_seconds, max_results=DIRECT_BIGQUERY_MAX_ROWS + 1
                    )
                    results = _fetch_capped_bigquery_rows(row_iterator)
                    schema_fields = list(row_iterator.schema or [])
        except Exception as error:
            # The auth error classes stay inside warehouse_sources; the facade exposes a
            # predicate for them instead.
            handled = isinstance(
                error,
                futures.TimeoutError
                | google_api_exceptions.GoogleAPIError
                | google_auth_exceptions.GoogleAuthError
                | ExposedHogQLError,
            ) or is_bigquery_auth_error(error)
            if not handled:
                raise
            span.set_attribute("error_type", error.__class__.__name__)
            message = (
                DIRECT_BIGQUERY_TIMEOUT_ERROR
                if isinstance(error, futures.TimeoutError)
                else bigquery_error_to_message(error)
            )
            if request.debug:
                return DirectQueryResult(results=[], types=[], print_columns=[], error=message)
            raise ExposedHogQLError(message) from error

        span.set_attribute("row_count", len(results))
        types: list[tuple[str, str]] = [
            (field.name, bigquery_field_to_clickhouse_type(field.field_type, field.mode)) for field in schema_fields
        ]
        print_columns = [field.name for field in schema_fields]
        return DirectQueryResult(results=results, types=types, print_columns=print_columns)
