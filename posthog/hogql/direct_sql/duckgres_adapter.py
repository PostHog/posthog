from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Generator, Iterator
from contextlib import closing, contextmanager
from dataclasses import field
from itertools import chain
from selectors import DefaultSelector
from time import monotonic
from typing import TYPE_CHECKING, cast

import psycopg
import structlog
from opentelemetry import trace
from psycopg import pq
from psycopg.abc import Params, PQGen, PQGenConn, Query
from psycopg.conninfo import make_conninfo
from psycopg.generators import fetch, send
from psycopg.waiting import Ready

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_query_metrics import DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL, observe_direct_query
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.pgwire import (
    MANAGED_WAREHOUSE_CONNECTION_ERROR,
    LenientDirectPostgresDateLoader,
    postgres_error_to_message,
    postgres_oid_to_clickhouse_type,
)
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError

from posthog.dataclasses import frozen
from posthog.direct_query_cancellation import is_direct_query_cancellation_requested
from posthog.psycopg_helpers import resolve_psycopg_hostaddr_with_timeout

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceAuth, ServiceCredentialUnavailable
from products.managed_warehouse.backend.facade.sql_editor import resolve_managed_warehouse_postgres_connection
from products.warehouse_sources.backend.facade.models import MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND

if TYPE_CHECKING:
    from psycopg.pq.abc import PGresult

    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource


DIRECT_DUCKGRES_CONNECT_TIMEOUT_SECONDS = 15
DIRECT_DUCKGRES_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
DIRECT_DUCKGRES_CANCEL_MAX_ATTEMPTS = 3
DIRECT_DUCKGRES_CANCEL_RETRY_SECONDS = 0.25
DIRECT_DUCKGRES_CANCEL_TIMEOUT_SECONDS = 1
DIRECT_DUCKGRES_CANCELLATION_POLL_SECONDS = 1
DIRECT_DUCKGRES_CANCEL_JOIN_SECONDS = (
    DIRECT_DUCKGRES_CANCEL_MAX_ATTEMPTS * DIRECT_DUCKGRES_CANCEL_TIMEOUT_SECONDS
    + (DIRECT_DUCKGRES_CANCEL_MAX_ATTEMPTS - 1) * DIRECT_DUCKGRES_CANCEL_RETRY_SECONDS
    + 1
)
DIRECT_DUCKGRES_MAX_ROWS = 50_000
DIRECT_DUCKGRES_ROW_CAP_ERROR = (
    f"Managed warehouse query returned more than {DIRECT_DUCKGRES_MAX_ROWS:,} rows. Add a LIMIT clause."
)
MANAGED_WAREHOUSE_UNAVAILABLE_ERROR = "Managed warehouse is unavailable. Contact support if the problem persists."
MANAGED_WAREHOUSE_TIMEOUT_ERROR = "Managed warehouse query exceeded the execution time limit."
MANAGED_WAREHOUSE_CANCELED_ERROR = "Managed warehouse query was canceled."

logger = structlog.get_logger(__name__)


@frozen
class _DuckgresConnectionConfig:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)


@frozen
class _DuckgresCancellationState:
    timed_out: threading.Event = field(default_factory=threading.Event)
    canceled: threading.Event = field(default_factory=threading.Event)


class _DuckgresStreamingClientCursor(psycopg.ClientCursor[tuple[object, ...]]):
    # Psycopg 3.2.4's stream() drops empty-result metadata and rejects successful commands.
    # Preserve its single-row decoding while retaining the terminal libpq result.
    def _stream_send_gen(
        self,
        query: Query,
        params: Params | None = None,
        *,
        binary: bool | None = None,
        size: int,
    ) -> PQGen[None]:
        if size != 1:
            raise ValueError("Duckgres streaming only supports one row per result chunk")

        yield from self._start_query(query)
        postgres_query = self._convert_query(query, params)
        self._execute_send(postgres_query, binary=binary)
        self._pgconn.set_single_row_mode()
        self._last_query = query
        yield from send(self._pgconn)

    def _stream_fetchone_gen(self, first: bool) -> PQGen[PGresult | None]:
        result: PGresult | None = yield from fetch(self._pgconn)
        if result is None:
            return None

        if result.status in (pq.ExecStatus.SINGLE_TUPLE, pq.ExecStatus.TUPLES_CHUNK):
            self.pgresult = result
            self._tx.set_pgresult(result, set_loaders=first)
            if first:
                self._make_row = self._make_row_maker()
            return result

        if result.status in (pq.ExecStatus.EMPTY_QUERY, pq.ExecStatus.TUPLES_OK, pq.ExecStatus.COMMAND_OK):
            terminal_result = result
            while result is not None:
                result = yield from fetch(self._pgconn)
            self._set_results([terminal_result])
            return None

        return self._raise_for_result(result)


@contextmanager
def _cancel_duckgres_query_on_signal(
    connection: psycopg.Connection,
    timeout_seconds: int,
    team_id: int,
    cancellation_token: str | None,
) -> Iterator[_DuckgresCancellationState]:
    state = _DuckgresCancellationState()
    stop_canceling = threading.Event()
    interrupt_started = threading.Event()
    interrupt_lock = threading.Lock()

    def interrupt_query(reason: str, signal: threading.Event) -> None:
        with interrupt_lock:
            if stop_canceling.is_set() or interrupt_started.is_set():
                return
            interrupt_started.set()
            signal.set()
        cancellation_failure_logged = False
        for attempt in range(DIRECT_DUCKGRES_CANCEL_MAX_ATTEMPTS):
            if stop_canceling.is_set():
                return
            try:
                connection.cancel_safe(timeout=DIRECT_DUCKGRES_CANCEL_TIMEOUT_SECONDS)
            except Exception:
                if not cancellation_failure_logged:
                    logger.warning("Failed to cancel managed warehouse query", reason=reason)
                    cancellation_failure_logged = True
            if attempt < DIRECT_DUCKGRES_CANCEL_MAX_ATTEMPTS - 1 and stop_canceling.wait(
                DIRECT_DUCKGRES_CANCEL_RETRY_SECONDS
            ):
                return
        if stop_canceling.is_set():
            return
        try:
            interrupt_socket = socket.socket(fileno=connection.pgconn.socket)
            try:
                interrupt_socket.shutdown(socket.SHUT_RDWR)
            finally:
                # The request thread owns libpq's descriptor and closes it after the interrupted operation unwinds.
                interrupt_socket.detach()
        except Exception:
            logger.warning("Failed to interrupt managed warehouse connection", reason=reason)

    def cancel_at_deadline() -> None:
        interrupt_query("execution deadline", state.timed_out)

    def watch_for_cancellation() -> None:
        cancellation_check_failure_logged = False
        while not stop_canceling.is_set():
            try:
                if cancellation_token is not None and is_direct_query_cancellation_requested(
                    team_id, cancellation_token
                ):
                    interrupt_query("user request", state.canceled)
                    return
            except Exception:
                if not cancellation_check_failure_logged:
                    logger.warning("Failed to check for managed warehouse query cancellation")
                    cancellation_check_failure_logged = True
            if stop_canceling.wait(DIRECT_DUCKGRES_CANCELLATION_POLL_SECONDS):
                return

    timer = threading.Timer(timeout_seconds, cancel_at_deadline)
    timer.daemon = True
    timer.start()
    cancellation_watcher: threading.Thread | None = None
    if cancellation_token is not None:
        cancellation_watcher = threading.Thread(target=watch_for_cancellation, daemon=True)
        cancellation_watcher.start()
    try:
        yield state
    finally:
        stop_canceling.set()
        timer.cancel()
        timer.join(DIRECT_DUCKGRES_CANCEL_JOIN_SECONDS)
        if cancellation_watcher is not None:
            cancellation_watcher.join(DIRECT_DUCKGRES_CANCEL_JOIN_SECONDS)


def _fetch_capped_duckgres_rows(row_stream: Iterator[tuple[object, ...]]) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for row in row_stream:
        rows.append(row)
        if len(rows) > DIRECT_DUCKGRES_MAX_ROWS:
            DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL.labels(dialect="duckgres").inc()
            raise ExposedHogQLError(DIRECT_DUCKGRES_ROW_CAP_ERROR)
    return rows


def _wait_for_duckgres_connection(
    generator: PQGenConn[psycopg.Connection[tuple[object, ...]]],
    deadline: float,
    abort_check: Callable[[], None],
) -> psycopg.Connection[tuple[object, ...]]:
    try:
        fileno, wait = next(generator)
        with DefaultSelector() as selector:
            selector.register(fileno, wait)
            while True:
                abort_check()
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    raise psycopg.errors.ConnectionTimeout("connection timeout expired")

                ready_events = selector.select(
                    timeout=min(remaining_seconds, DIRECT_DUCKGRES_CANCELLATION_POLL_SECONDS)
                )
                if not ready_events:
                    generator.send(Ready.NONE)
                    continue

                selector.unregister(fileno)
                fileno, wait = generator.send(Ready(ready_events[0][1]))
                selector.register(fileno, wait)
    except StopIteration as stop:
        return stop.value
    finally:
        generator.close()


def _connect_duckgres_address(
    source_config: _DuckgresConnectionConfig,
    hostaddr: str | None,
    deadline: float,
    abort_check: Callable[[], None],
) -> psycopg.Connection[tuple[object, ...]]:
    remaining_seconds = deadline - monotonic()
    if remaining_seconds <= 0:
        raise psycopg.errors.ConnectionTimeout("connection timeout expired")

    conninfo = make_conninfo(
        "",
        host=source_config.host,
        hostaddr=hostaddr,
        port=source_config.port,
        dbname=source_config.database,
        user=source_config.user,
        password=source_config.password,
        sslmode="require",
        sslcert="/tmp/no.txt",
        sslkey="/tmp/no.txt",
        sslrootcert="/tmp/no.txt",
    )
    # The public connect API restarts connect_timeout for each address and offers no cancellation checkpoint.
    generator = cast(
        PQGenConn[psycopg.Connection[tuple[object, ...]]],
        psycopg.Connection._connect_gen(conninfo, timeout=remaining_seconds),
    )
    connection = _wait_for_duckgres_connection(generator, deadline, abort_check)
    connection.cursor_factory = _DuckgresStreamingClientCursor
    return connection


def _connect_duckgres_project_reader(
    source_config: _DuckgresConnectionConfig,
    team_id: int,
    cancellation_token: str | None,
) -> psycopg.Connection[tuple[object, ...]]:
    deadline = monotonic() + DIRECT_DUCKGRES_CONNECT_TIMEOUT_SECONDS
    cancellation_check_failure_logged = False

    def abort_if_canceled() -> None:
        nonlocal cancellation_check_failure_logged
        if cancellation_token is None:
            return
        try:
            canceled = is_direct_query_cancellation_requested(team_id, cancellation_token)
        except Exception:
            if not cancellation_check_failure_logged:
                logger.warning("Failed to check for managed warehouse query cancellation while connecting")
                cancellation_check_failure_logged = True
            return
        if canceled:
            raise ExposedHogQLError(MANAGED_WAREHOUSE_CANCELED_ERROR)

    abort_if_canceled()
    remaining_seconds = deadline - monotonic()
    if remaining_seconds <= 0:
        raise psycopg.errors.ConnectionTimeout("connection timeout expired")
    addresses = resolve_psycopg_hostaddr_with_timeout(
        source_config.host,
        source_config.port,
        remaining_seconds,
        fail_on_resolution_error=True,
        abort_check=abort_if_canceled,
    )

    connection_addresses: list[str | None]
    if addresses is None:
        connection_addresses = [None]
    else:
        connection_addresses = list(addresses)
    last_error: psycopg.Error | None = None
    for hostaddr in connection_addresses:
        abort_if_canceled()
        if deadline - monotonic() <= 0:
            raise psycopg.errors.ConnectionTimeout("connection timeout expired") from last_error
        try:
            return _connect_duckgres_address(source_config, hostaddr, deadline, abort_if_canceled)
        except psycopg.Error as error:
            last_error = error

    if last_error is not None:
        raise last_error
    raise psycopg.OperationalError("Could not connect to managed warehouse")


class DuckgresRawAdapter:
    engine = "duckgres"
    dialect: HogQLDialect | None = None

    def validate_source_config(self, source: ExternalDataSource, team: Team) -> tuple[None, _DuckgresConnectionConfig]:
        if source.team_id != team.pk or not source.is_managed_warehouse_ready:
            raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR)

        job_inputs = source.job_inputs
        if not isinstance(job_inputs, dict):
            raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR)

        host = job_inputs.get("host")
        database = job_inputs.get("database")
        user = job_inputs.get("user")
        password = job_inputs.get("password")
        raw_port = job_inputs.get("port")
        if (
            not isinstance(host, str)
            or not host.strip()
            or not isinstance(database, str)
            or not database.strip()
            or not isinstance(user, str)
            or user != f"posthog_team_{team.pk}"
            or not isinstance(password, str)
            or not password
            or isinstance(raw_port, bool)
        ):
            raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR)

        if isinstance(raw_port, int):
            port = raw_port
        elif isinstance(raw_port, str) and raw_port.isdigit():
            port = int(raw_port)
        else:
            raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR)
        if not 1 <= port <= 65535:
            raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR)

        return None, _DuckgresConnectionConfig(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
        )

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_single_direct_statement(sql)

    def _resolve_source_config(self, request: DirectQueryRequest) -> _DuckgresConnectionConfig:
        metadata = request.source.connection_metadata
        credential_kind = metadata.get("credential_kind") if isinstance(metadata, dict) else None
        lifecycle_generation = metadata.get("lifecycle_generation") if isinstance(metadata, dict) else None
        if credential_kind != MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND:
            return self.validate_source_config(request.source, request.team)[1]
        if not request.source.is_dynamic_managed_warehouse or request.principal is None:
            raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR)

        try:
            connection = resolve_managed_warehouse_postgres_connection(
                source_auth=ManagedWarehouseSourceAuth(
                    prefix=request.source.prefix,
                    system_managed=request.source.is_system_managed,
                    credential_kind=credential_kind,
                    lifecycle_generation=(lifecycle_generation if isinstance(lifecycle_generation, int) else None),
                ),
                organization_id=request.team.organization_id,
                team_id=request.team.pk,
                principal=request.principal.value,
            )
        except ServiceCredentialUnavailable as error:
            raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR) from error
        if connection is None or connection.sslmode != "require":
            raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR)
        return _DuckgresConnectionConfig(
            host=connection.host,
            port=connection.port,
            database=connection.database,
            user=connection.username,
            password=connection.password,
        )

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        statement_timeout_seconds = max(
            request.settings.max_execution_time or DIRECT_DUCKGRES_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1
        )
        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(request.source.id))
        cancellation: _DuckgresCancellationState | None = None

        try:
            with request.timings.measure("duckgres_execute"), observe_direct_query("duckgres"):
                with request.timings.measure("duckgres_source_validation"):
                    source_config = self._resolve_source_config(request)
                try:
                    with request.timings.measure("duckgres_connect", emit_span=True):
                        connection_context = _connect_duckgres_project_reader(
                            source_config,
                            request.team.pk,
                            request.cancellation_token,
                        )
                except (RuntimeError, ValueError) as error:
                    span.set_attribute("error_type", error.__class__.__name__)
                    raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR) from error
                except psycopg.Error as error:
                    span.set_attribute("error_type", error.__class__.__name__)
                    raise ExposedHogQLError(MANAGED_WAREHOUSE_CONNECTION_ERROR) from error

                with connection_context as connection:
                    with _cancel_duckgres_query_on_signal(
                        connection,
                        statement_timeout_seconds,
                        request.team.pk,
                        request.cancellation_token,
                    ) as cancellation:
                        with request.timings.measure("duckgres_session_setup"):
                            connection.execute("USE ducklake")
                        connection.adapters.register_loader("date", LenientDirectPostgresDateLoader)
                        with connection.cursor() as cursor:
                            row_stream = cast(
                                Generator[tuple[object, ...]],
                                cursor.stream(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute
                                    request.sql, request.values or None
                                ),
                            )
                            with closing(row_stream):
                                with request.timings.measure("duckgres_query_execute", emit_span=True):
                                    try:
                                        first_row = next(row_stream)
                                    except StopIteration:
                                        first_row = None
                                with request.timings.measure("duckgres_query_fetch"):
                                    results = (
                                        _fetch_capped_duckgres_rows(chain((first_row,), row_stream))
                                        if first_row is not None
                                        else []
                                    )
                            if cancellation.canceled.is_set():
                                raise ExposedHogQLError(MANAGED_WAREHOUSE_CANCELED_ERROR)
                            if cancellation.timed_out.is_set():
                                raise ExposedHogQLError(MANAGED_WAREHOUSE_TIMEOUT_ERROR)
                            description = cursor.description or []
                        with request.timings.measure("duckgres_commit", emit_span=True):
                            connection.commit()
                        if cancellation.canceled.is_set():
                            raise ExposedHogQLError(MANAGED_WAREHOUSE_CANCELED_ERROR)
                        if cancellation.timed_out.is_set():
                            raise ExposedHogQLError(MANAGED_WAREHOUSE_TIMEOUT_ERROR)
        except (psycopg.Error, ExposedHogQLError) as error:
            span.set_attribute("error_type", error.__class__.__name__)
            if cancellation is not None and cancellation.canceled.is_set():
                error = ExposedHogQLError(MANAGED_WAREHOUSE_CANCELED_ERROR)
            elif cancellation is not None and cancellation.timed_out.is_set():
                error = ExposedHogQLError(MANAGED_WAREHOUSE_TIMEOUT_ERROR)
            elif isinstance(error, psycopg.OperationalError):
                error = ExposedHogQLError(MANAGED_WAREHOUSE_CONNECTION_ERROR)
            if request.debug:
                return DirectQueryResult(results=[], types=[], print_columns=[], error=postgres_error_to_message(error))
            raise ExposedHogQLError(postgres_error_to_message(error)) from error

        span.set_attribute("row_count", len(results))
        types = [
            (column.name, postgres_oid_to_clickhouse_type(getattr(column, "type_code", None))) for column in description
        ]
        return DirectQueryResult(results=results, types=types, print_columns=[column.name for column in description])
