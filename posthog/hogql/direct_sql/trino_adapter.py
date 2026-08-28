from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

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
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import (
        TrinoSourceConfig,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.trino.source import TrinoSource


DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
DIRECT_TRINO_MAX_ROWS = 1_000_000
RAW_TRINO_READ_ONLY_ERROR = "Raw Trino queries must be read-only SELECT statements."
DIRECT_TRINO_ROW_CAP_ERROR = f"Trino query returned more than {DIRECT_TRINO_MAX_ROWS:,} rows. Add a LIMIT clause."
DIRECT_TRINO_TIMEOUT_ERROR = "Trino query timed out."


def ensure_read_only_raw_trino_statement(sql: str) -> str:
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1 or statements[0].get_type() != "SELECT":
        raise ExposedHogQLError(RAW_TRINO_READ_ONLY_ERROR)
    for token in statements[0].flatten():
        if token.ttype in sqlparse_tokens.DDL:
            raise ExposedHogQLError(RAW_TRINO_READ_ONLY_ERROR)
        if token.ttype in sqlparse_tokens.DML and token.value.upper() != "SELECT":
            raise ExposedHogQLError(RAW_TRINO_READ_ONLY_ERROR)
    return sql


class _CancelWatchdog:
    def __init__(self, cursor: object, timeout_seconds: float) -> None:
        self._fired = threading.Event()

        def _cancel() -> None:
            self._fired.set()
            try:
                cursor.cancel()  # type: ignore[attr-defined]
            except Exception:
                pass

        self._timer = threading.Timer(timeout_seconds, _cancel)
        self._timer.daemon = True

    def __enter__(self) -> _CancelWatchdog:
        self._timer.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._timer.cancel()

    @property
    def fired(self) -> bool:
        return self._fired.is_set()


class TrinoAdapter:
    engine = "trino"
    dialect: HogQLDialect | None = None

    def validate_source_config(self, source: ExternalDataSource, team: Team) -> tuple[TrinoSource, TrinoSourceConfig]:
        from products.warehouse_sources.backend.facade.source_management import (
            SourceRegistry,  # noqa: PLC0415 — avoids loading every source during HogQL startup
        )
        from products.warehouse_sources.backend.facade.types import (
            ExternalDataSourceType,  # noqa: PLC0415 — product boundary is loaded only for direct queries
        )

        if not (is_direct_capable(source) and source.direct_engine == self.engine):
            raise ExposedHogQLError("Invalid direct Trino connection.")

        trino_source = cast("TrinoSource", SourceRegistry.get_source(ExternalDataSourceType.TRINO))
        config = trino_source.parse_config(source.job_inputs or {})
        is_valid, error = trino_source.is_database_host_valid(config.host, team.pk)
        if not is_valid:
            raise ExposedHogQLError(error or "Invalid Trino host.")
        return trino_source, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_trino_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        from products.warehouse_sources.backend.facade.models import (
            trino_column_to_dwh_column,  # noqa: PLC0415 — product mapper is needed only for Trino results
        )
        from products.warehouse_sources.backend.facade.source_management import (  # noqa: PLC0415 — keeps the optional driver off startup paths
            connect_trino,
            trino_error_to_message,
        )

        _, config = self.validate_source_config(request.source, request.team)
        timeout_seconds = max(
            request.settings.max_execution_time or DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS,
            1,
        )
        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(request.source.id))

        try:
            with request.timings.measure("trino_execute"), observe_direct_query("trino"):
                with connect_trino(config) as connection:
                    cursor = connection.cursor()
                    with _CancelWatchdog(cursor, timeout_seconds) as watchdog:
                        try:
                            cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute -- direct SQL is intentionally user-authored and SELECT-gated
                                request.sql
                            )
                            results = cursor.fetchmany(DIRECT_TRINO_MAX_ROWS + 1)
                        except Exception as error:
                            if watchdog.fired:
                                raise ExposedHogQLError(DIRECT_TRINO_TIMEOUT_ERROR) from error
                            raise
                    description = cursor.description or []
        except Exception as error:
            span.set_attribute("error_type", error.__class__.__name__)
            message = str(error) if isinstance(error, ExposedHogQLError) else trino_error_to_message(error)
            if request.debug:
                return DirectQueryResult(results=[], types=[], print_columns=[], error=message)
            if isinstance(error, ExposedHogQLError):
                raise
            raise ExposedHogQLError(message) from error

        if len(results) > DIRECT_TRINO_MAX_ROWS:
            DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL.labels(dialect="trino").inc()
            raise ExposedHogQLError(DIRECT_TRINO_ROW_CAP_ERROR)

        span.set_attribute("row_count", len(results))
        types = []
        for column in description:
            mapped = trino_column_to_dwh_column(str(column[0]), str(column[1]), True)
            types.append((str(column[0]), str(mapped["clickhouse"])))
        return DirectQueryResult(
            results=list(results),
            types=types,
            print_columns=[str(column[0]) for column in description],
        )
