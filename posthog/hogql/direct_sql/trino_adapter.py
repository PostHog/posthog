from __future__ import annotations

import time
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any, cast

import sqlparse
import structlog
from opentelemetry import trace
from sqlparse import tokens as sqlparse_tokens

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_query_metrics import DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL, observe_direct_query
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult, parse_direct_source_config
from posthog.hogql.direct_sql.capability import is_direct_capable
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from posthog.dataclasses import frozen
from posthog.direct_query_cancellation import is_direct_query_cancellation_requested

if TYPE_CHECKING:
    from trino.dbapi import Connection, Cursor

    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import (
        TrinoSourceConfig,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.trino.source import TrinoSource


log = structlog.get_logger(__name__)

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
    def __init__(
        self, cursor: Cursor, timeout_seconds: float, *, team_id: int = 0, cancellation_token: str | None = None
    ) -> None:
        self._fired = threading.Event()
        self._finished = threading.Event()
        self._cancelled = threading.Event()
        self._cancel_lock = threading.Lock()
        self._team_id = team_id
        self._cancellation_token = cancellation_token
        self._cursor = cursor
        self.deadline = time.monotonic() + max(timeout_seconds, 1)
        self._timer = threading.Timer(max(timeout_seconds, 1), self._fired.set)
        self._timer.daemon = True
        self._thread = threading.Thread(target=self._watch_cancellation, daemon=True, name="trino-query-cancel")

    def __enter__(self) -> _CancelWatchdog:
        self._timer.start()
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        with self._cancel_lock:
            self._finished.set()
        self._timer.cancel()
        # A Redis poll may outlive the query. The lock and finished check prevent it from touching a closed cursor.
        self._thread.join(timeout=1)

    def _watch_cancellation(self) -> None:
        delay = 0.5
        while not self._finished.wait(delay):
            try:
                if (
                    not self.cancelled
                    and self._cancellation_token
                    and is_direct_query_cancellation_requested(self._team_id, self._cancellation_token)
                ):
                    self._cancelled.set()
                if self.cancelled or self.fired:
                    with self._cancel_lock:
                        if self._finished.is_set():
                            return
                        self._cursor.cancel()
                delay = 0.5
            except Exception:
                if delay == 0.5:
                    log.warning("trino.cancellation_poll_failed", team_id=self._team_id, exc_info=True)
                delay = min(delay * 2, 5)

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            self._fired.set()
        if self.cancelled:
            raise ExposedHogQLError("Trino query was canceled.")
        if self.fired:
            raise ExposedHogQLError(DIRECT_TRINO_TIMEOUT_ERROR)

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def fired(self) -> bool:
        return self._fired.is_set()


@contextmanager
def bounded_trino_cursor(
    connection: Connection, timeout_seconds: float, *, team_id: int = 0, cancellation_token: str | None = None
) -> Iterator[tuple[Cursor, _CancelWatchdog]]:
    cursor = connection.cursor()
    watchdog = _CancelWatchdog(cursor, timeout_seconds, team_id=team_id, cancellation_token=cancellation_token)
    # The driver shares this session with capability probes and PREPARE, which cursor.cancel() cannot reach.
    session = connection._http_session
    original_request = session.request
    original_delete = cursor._request._delete

    def bounded_request(method: str, url: str, **kwargs: Any) -> Any:
        if method.upper() == "DELETE":
            remaining = 1.0
        else:
            watchdog.check()
            remaining = max(watchdog.deadline - time.monotonic(), 0.001)
        timeout = kwargs.get("timeout")
        if isinstance(timeout, tuple):
            kwargs["timeout"] = tuple(min(value or remaining / 2, remaining / 2) for value in timeout)
        else:
            kwargs["timeout"] = min(timeout or remaining / 2, remaining / 2)
        return original_request(method, url, **kwargs)

    session.request = bounded_request  # type: ignore[method-assign, assignment]  # ty: ignore[invalid-assignment]
    # Cancellation gets one bounded HTTP attempt; driver retries would extend the statement deadline during cleanup.
    cursor._request._delete = session.delete
    try:
        with watchdog:
            yield cursor, watchdog
    finally:
        try:
            cursor.close()
        except Exception:
            log.warning("trino.cursor_cleanup_failed", team_id=team_id, exc_info=True)
        finally:
            session.request = original_request  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
            cursor._request._delete = original_delete


@frozen
class TrinoQueryRequest:
    sql: str
    values: dict[str, object] | None
    timeout_seconds: float
    timings: HogQLTimings
    team_id: int
    debug: bool = False
    cancellation_token: str | None = None


def execute_trino_query(
    request: TrinoQueryRequest, connection_context: AbstractContextManager[Connection]
) -> DirectQueryResult:
    from products.warehouse_sources.backend.facade.models import (
        trino_column_to_dwh_column,  # noqa: PLC0415 -- optional result mapping belongs to warehouse sources
    )
    from products.warehouse_sources.backend.facade.source_management import (
        trino_error_to_message,  # noqa: PLC0415 -- avoids loading connector drivers during Django startup
    )

    span = trace.get_current_span()
    span.set_attribute("team_id", request.team_id)
    sql, values = (
        convert_pyformat_placeholders(request.sql, request.values) if request.values is not None else (request.sql, [])
    )
    try:
        with request.timings.measure("trino_execute"), observe_direct_query("trino"):
            with connection_context as connection:
                with bounded_trino_cursor(
                    connection,
                    request.timeout_seconds,
                    team_id=request.team_id,
                    cancellation_token=request.cancellation_token,
                ) as (cursor, watchdog):
                    try:
                        if values:
                            cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute -- values are passed as parameters; the trino client escapes them, this code never concatenates them
                                sql, values
                            )
                        else:
                            cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute -- raw SQL is intentionally user-authored and SELECT-gated
                                sql
                            )
                        results = cursor.fetchmany(DIRECT_TRINO_MAX_ROWS + 1)
                    except Exception:
                        watchdog.check()
                        raise
                    watchdog.check()
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


class TrinoAdapter:
    engine = "trino"
    dialect: HogQLDialect | None = "trino"

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
        config = parse_direct_source_config(trino_source, source)
        is_valid, error = trino_source.is_database_host_valid(config.host, team.pk)
        if not is_valid:
            raise ExposedHogQLError(error or "Invalid Trino host.")
        return trino_source, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_trino_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        from products.warehouse_sources.backend.facade.source_management import (  # noqa: PLC0415 — keeps the optional driver off startup paths
            connect_trino,
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
        return execute_trino_query(
            TrinoQueryRequest(
                sql=request.sql,
                values=request.values,
                timeout_seconds=timeout_seconds,
                timings=request.timings,
                team_id=request.team.pk,
                debug=request.debug,
                cancellation_token=request.cancellation_token,
            ),
            connect_trino(config),
        )
