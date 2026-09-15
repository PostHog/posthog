"""Drain person_pg_cleanup_queue into Postgres hard deletes.

The ClickHouse sweep (clickhouse_cleanup.py) removes a deleted person's rows from ClickHouse and
queues the person here. Postgres still holds the tombstoned posthog_person row and its dependent
rows (distinct ids, hash key overrides, cohort memberships) until this job asks personhog to
delete them.

The queue is advisory. A person can be revived in Postgres after it was queued, so the job never
deletes on the queue's word: it hands each batch to personhog's DeleteTombstonedPersons, which
deletes a person only while it is still tombstoned, under row locks, and reports the rest back.
Every call does a bounded amount of work: persons that fit the call's row budget are deleted
whole, and a person with more dependent rows than that gives up a bounded slice per call and
comes back as pending until it fits. The job sends pending persons again until none come back, so
a person of any size is deleted in steps that each fit the router's deadline; run time is what
gives. Queue rows are removed once personhog has resolved the person either way.

A run fails only when a dependency is down or broken: a request that keeps failing for the whole
retry window, a Postgres statement that keeps failing for its window (a lost connection is
reopened and the statement run again), a fatal gRPC code, or more blocked persons than
max_blocked. The one state the job parks is a tombstoned person that still owns a live distinct
id: personhog reports it as blocked, and its row is stamped blocked_at and skipped for a retry
interval, because ingestion can still reach that person and no delete may resolve it.
"""

import math
import time
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Literal, TypeVar

import grpc
import dagster
import psycopg2
import pydantic
import psycopg2.extensions

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags.clickhouse_cleanup import PG_CLEANUP_QUEUE_TABLE
from posthog.dags.common import JobOwners
from posthog.dataclasses import frozen
from posthog.personhog_client.client import PersonHogClient, personhog_call, require_personhog_client
from posthog.personhog_client.proto import DeleteTombstonedPersonsRequest, DeleteTombstonedPersonsResponse

logger = dagster.get_dagster_logger(__name__)

PERSONHOG_CALLER_TAG = "clickhouse_cleanup/person-pg-drain"
PG_APPLICATION_NAME = "person_pg_cleanup_drain"

# Server-side cap on DeleteTombstonedPersonsRequest.person_uuids.
RPC_MAX_UUIDS = 1000

# personhog-router caps every backend call at BACKEND_TIMEOUT_MS whatever the client deadline. The
# replica deletes at most REPLICA_CHUNK_SIZE persons per call (its BULK_CHUNK_SIZE) and clamps the
# row budget to REPLICA_MAX_ROWS (its TOMBSTONED_DELETE_MAX_ROWS).
ROUTER_BACKEND_TIMEOUT_SECONDS = 5.0
REPLICA_CHUNK_SIZE = 100
REPLICA_MAX_ROWS = 5000

# Dependent rows per request: start here, halve after a timeout down to the floor, double after
# STEP_GROWTH_SUCCESSES requests in a row succeeded. The persons tables cost up to 5 ms per row at
# the tail, so the floor still fits the router's deadline on a bad day.
STEP_START_ROWS = 500
STEP_FLOOR_ROWS = 100
STEP_GROWTH_SUCCESSES = 20

RETRY_BACKOFF_CAP_SECONDS = 60.0
PG_RETRY_BACKOFF_SECONDS = 1.0
LOG_EVERY_PAGES = 10
BLOCKED_SAMPLE_SIZE = 50

# Codes that say the request itself is wrong or unserved; another attempt returns the same answer.
FATAL_RPC_CODES = frozenset(
    {
        grpc.StatusCode.UNIMPLEMENTED,
        grpc.StatusCode.INVALID_ARGUMENT,
        grpc.StatusCode.PERMISSION_DENIED,
        grpc.StatusCode.UNAUTHENTICATED,
    }
)
# Codes a request that outran the router's deadline comes back with: the router answers
# UNAVAILABLE once its own retries of the backend call time out.
SLOW_RPC_CODES = frozenset({grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.UNAVAILABLE})

_T = TypeVar("_T")


class DrainConfig(dagster.Config):
    dry_run: bool = pydantic.Field(
        default=True,
        description="Page and count the queue without calling personhog or writing to Postgres.",
    )
    max_persons: int = pydantic.Field(
        default=0,
        description="Stop after reading this many queue rows, 0 for no cap. A capped run leaves the rest for the "
        "next run.",
    )
    page_size: int = pydantic.Field(default=1000, description="Queue rows per Postgres read, at most 1000.")
    rpc_batch_size: int = pydantic.Field(
        default=REPLICA_CHUNK_SIZE,
        description="Person uuids per personhog request, at most 1000. The replica deletes at most 100 persons per "
        "call and returns the rest as pending, so more only adds re-sends.",
    )
    max_rows_per_request: int = pydantic.Field(
        default=2000,
        description=f"Most dependent rows one personhog request may delete, between {STEP_FLOOR_ROWS} and "
        f"{REPLICA_MAX_ROWS}. Requests start at {STEP_START_ROWS} rows and grow toward this after runs of "
        "successes; a timeout halves the step.",
    )
    pause_ms: int = pydantic.Field(default=200, description="Pause after every personhog request.")
    latency_multiplier: float = pydantic.Field(
        default=1.0,
        description="Extra pause after every request, as a multiple of that request's latency. When the persons "
        "writer slows down, the drain slows down with it.",
    )
    rpc_timeout_seconds: float = pydantic.Field(
        default=ROUTER_BACKEND_TIMEOUT_SECONDS,
        description="Deadline per personhog request. personhog-router caps every backend call at 5 s and re-sends "
        "a timed-out call, so a longer deadline only lets one slow step run several times.",
    )
    max_runtime_seconds: int = pydantic.Field(
        default=24 * 3600,
        description="Stop taking new pages and requests after this many seconds, then finish cleanly; 0 means no "
        "cap. Rows left over wait for the next run; rows already deleted stay deleted.",
    )
    retry_backoff_seconds: float = pydantic.Field(
        default=2.0,
        description="Pause before the retry of a failed personhog request. Doubles per consecutive failure, capped "
        "at 60 s.",
    )
    rpc_retry_window_seconds: float = pydantic.Field(
        default=3600.0,
        description="Keep retrying one failing personhog request for this long before the run fails. Long enough "
        "to ride out a replica rollout, a database failover or a cold buffer cache; a run that fails here found "
        "personhog down.",
    )
    pg_retry_window_seconds: float = pydantic.Field(
        default=1800.0,
        description="Keep retrying one failing queue statement for this long, reconnecting after a lost connection, "
        "before the run fails.",
    )
    blocked_retry_hours: int = pydantic.Field(
        default=24, description="Skip rows stamped blocked_at more recently than this."
    )
    max_blocked: int = pydantic.Field(
        default=1000,
        description="Fail the run once more rows than this are stamped blocked_at in one run: tombstoned persons "
        "that still own a live distinct id. That many needs a person, not a retry.",
    )

    @pydantic.model_validator(mode="after")
    def validate_bounds(self) -> "DrainConfig":
        if not 1 <= self.page_size <= RPC_MAX_UUIDS:
            raise ValueError(f"page_size must be between 1 and {RPC_MAX_UUIDS}")
        if not 1 <= self.rpc_batch_size <= RPC_MAX_UUIDS:
            raise ValueError(f"rpc_batch_size must be between 1 and {RPC_MAX_UUIDS}")
        if not STEP_FLOOR_ROWS <= self.max_rows_per_request <= REPLICA_MAX_ROWS:
            raise ValueError(f"max_rows_per_request must be between {STEP_FLOOR_ROWS} and {REPLICA_MAX_ROWS}")
        if self.rpc_timeout_seconds <= 0:
            raise ValueError("rpc_timeout_seconds must be positive")
        if min(self.max_persons, self.max_runtime_seconds, self.pause_ms, self.latency_multiplier) < 0:
            raise ValueError("max_persons, max_runtime_seconds, pause_ms and latency_multiplier must not be negative")
        if self.blocked_retry_hours < 0:
            raise ValueError("blocked_retry_hours must not be negative")
        if (
            min(
                self.retry_backoff_seconds,
                self.rpc_retry_window_seconds,
                self.pg_retry_window_seconds,
                self.max_blocked,
            )
            < 0
        ):
            raise ValueError(
                "retry_backoff_seconds, rpc_retry_window_seconds, pg_retry_window_seconds and max_blocked must not "
                "be negative"
            )
        return self


@frozen
class QueueRow:
    team_id: int
    person_uuid: str
    deleted_at: datetime


@frozen
class QueueCursor:
    team_id: int
    person_uuid: str


@frozen
class Chunk:
    """One personhog request: persons of one team, queued by one sweep run."""

    team_id: int
    deleted_at: datetime
    person_uuids: tuple[str, ...]


@frozen(frozen=False)
class DrainTotals:
    rows_read: int = 0
    pages: int = 0
    chunks: int = 0
    rpc_calls: int = 0
    rpc_errors: int = 0
    requests_pending_resent: int = 0
    persons_deleted: int = 0
    persons_skipped_live: int = 0
    persons_not_found: int = 0
    persons_blocked: int = 0
    rows_deleted: int = 0
    rows_stamped_blocked: int = 0
    blocked_sample: list[str] = field(default_factory=list)
    queue_rows_deleted: int = 0
    step_rows_min: int = 0
    step_rows_max: int = 0
    pg_reconnects: int = 0
    rpc_seconds: list[float] = field(default_factory=list)
    pg_seconds_total: float = 0.0
    teams_touched: set[int] = field(default_factory=set)
    queue_rows_estimate_at_start: int = 0
    stopped_reason: str = "drained"

    def as_metadata(self) -> dict[str, dagster.MetadataValue]:
        return {
            "rows_read": dagster.MetadataValue.int(self.rows_read),
            "pages": dagster.MetadataValue.int(self.pages),
            "chunks": dagster.MetadataValue.int(self.chunks),
            "rpc_calls": dagster.MetadataValue.int(self.rpc_calls),
            "rpc_errors": dagster.MetadataValue.int(self.rpc_errors),
            "requests_pending_resent": dagster.MetadataValue.int(self.requests_pending_resent),
            "persons_deleted": dagster.MetadataValue.int(self.persons_deleted),
            "persons_skipped_live": dagster.MetadataValue.int(self.persons_skipped_live),
            "persons_not_found": dagster.MetadataValue.int(self.persons_not_found),
            "persons_blocked": dagster.MetadataValue.int(self.persons_blocked),
            "rows_deleted": dagster.MetadataValue.int(self.rows_deleted),
            "rows_stamped_blocked": dagster.MetadataValue.int(self.rows_stamped_blocked),
            "blocked_sample": dagster.MetadataValue.text(", ".join(self.blocked_sample) or "none"),
            "queue_rows_deleted": dagster.MetadataValue.int(self.queue_rows_deleted),
            "step_rows_min": dagster.MetadataValue.int(self.step_rows_min),
            "step_rows_max": dagster.MetadataValue.int(self.step_rows_max),
            "pg_reconnects": dagster.MetadataValue.int(self.pg_reconnects),
            "rpc_seconds_total": dagster.MetadataValue.float(round(sum(self.rpc_seconds, 0.0), 3)),
            "rpc_seconds_max": dagster.MetadataValue.float(round(max(self.rpc_seconds, default=0.0), 3)),
            "rpc_seconds_p50": dagster.MetadataValue.float(
                round(statistics.median(self.rpc_seconds), 3) if self.rpc_seconds else 0.0
            ),
            "pg_seconds_total": dagster.MetadataValue.float(round(float(self.pg_seconds_total), 3)),
            "teams_touched": dagster.MetadataValue.int(len(self.teams_touched)),
            "queue_rows_estimate_at_start": dagster.MetadataValue.int(self.queue_rows_estimate_at_start),
            "stopped_reason": dagster.MetadataValue.text(self.stopped_reason),
        }


def chunks_for_page(rows: Sequence[QueueRow], rpc_batch_size: int) -> list[Chunk]:
    """Group a page into personhog requests: one team and one sweep run per request.

    Grouping by deleted_at as well as team_id is what lets the queue delete carry a deleted_at
    guard, so a row the sweep re-queued between the read and the delete is left for the next run.
    """
    grouped: dict[tuple[int, datetime], list[str]] = defaultdict(list)
    for row in rows:
        grouped[(row.team_id, row.deleted_at)].append(row.person_uuid)
    return [
        Chunk(team_id=team_id, deleted_at=deleted_at, person_uuids=tuple(uuids[start : start + rpc_batch_size]))
        for (team_id, deleted_at), uuids in grouped.items()
        for start in range(0, len(uuids), rpc_batch_size)
    ]


PgRecovery = Literal["retry", "reconnect"]


def pg_recovery(exc: BaseException) -> PgRecovery | None:
    """How a failed queue statement can be run again, or None when it cannot."""
    if not isinstance(exc, psycopg2.Error):
        return None
    # Serialization failure, deadlock, lock_timeout and statement_timeout: the same connection
    # can simply run the statement again.
    if getattr(exc, "pgcode", None) in {"40001", "40P01", "55P03", "57014"}:
        return "retry"
    # psycopg2 raises OperationalError for a dropped or refused connection and InterfaceError for
    # a connection already closed; both need a new connection first.
    if isinstance(exc, psycopg2.OperationalError | psycopg2.InterfaceError):
        return "reconnect"
    return None


def pause_seconds(pause_ms: int, latency_multiplier: float, last_rpc_seconds: float) -> float:
    return pause_ms / 1000.0 + latency_multiplier * last_rpc_seconds


def backoff_seconds(base: float, failures: int) -> float:
    return min(base * 2 ** (failures - 1), RETRY_BACKOFF_CAP_SECONDS)


def _status_code(exc: grpc.RpcError) -> grpc.StatusCode | None:
    code = getattr(exc, "code", None)
    return code() if callable(code) else None


def _code_name(code: grpc.StatusCode | None) -> str:
    return code.name if code else "unknown"


def _now_monotonic() -> float:
    return time.monotonic()


def _pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _emit(metrics: MetricsClient, name: str, labels: Mapping[str, str], value: float = 1.0) -> None:
    """Record a counter, never letting telemetry fail the drain."""
    if value <= 0:
        return
    try:
        metrics.increment(name, labels=dict(labels), value=value).result()
    except Exception:
        logger.warning("failed to record %s", name, exc_info=True)


def _connect(persons_database_url: str) -> psycopg2.extensions.connection:
    # Autocommit: one statement per transaction, so no transaction stays open on the persons
    # writer across a personhog call or a pause.
    connection = psycopg2.connect(persons_database_url, connect_timeout=10)
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("SET application_name = %s", (PG_APPLICATION_NAME,))
        cursor.execute("SET statement_timeout = '30s'")
        cursor.execute("SET lock_timeout = '5s'")
    return connection


def _read_page(
    cursor: psycopg2.extensions.cursor,
    after: QueueCursor | None,
    limit: int,
    blocked_before: datetime,
) -> list[QueueRow]:
    # Keyset over the primary key. Drained rows are gone, so the walk never revisits them, and
    # the cursor carries the run past rows it left in place (blocked ones).
    cursor_filter = "AND (team_id, person_uuid) > (%(after_team)s, %(after_uuid)s::uuid)" if after else ""
    cursor.execute(
        f"""
        SELECT team_id, person_uuid, deleted_at
        FROM {PG_CLEANUP_QUEUE_TABLE}
        WHERE (blocked_at IS NULL OR blocked_at < %(blocked_before)s)
          {cursor_filter}
        ORDER BY team_id, person_uuid
        LIMIT %(limit)s
        """,
        {
            "after_team": after.team_id if after else 0,
            "after_uuid": after.person_uuid if after else "00000000-0000-0000-0000-000000000000",
            "blocked_before": blocked_before,
            "limit": limit,
        },
    )
    return [
        QueueRow(team_id=team_id, person_uuid=str(person_uuid), deleted_at=deleted_at)
        for team_id, person_uuid, deleted_at in cursor.fetchall()
    ]


def _delete_queue_rows(cursor: psycopg2.extensions.cursor, chunk: Chunk, person_uuids: Sequence[str]) -> int:
    if not person_uuids:
        return 0
    # The deleted_at guard leaves a row the sweep re-queued (new deleted_at) between our read and
    # this delete; that person is drained again on the strength of the newer tombstone.
    cursor.execute(
        f"""
        DELETE FROM {PG_CLEANUP_QUEUE_TABLE}
        WHERE team_id = %s AND deleted_at = %s AND person_uuid = ANY(%s::uuid[])
        """,
        (chunk.team_id, chunk.deleted_at, list(person_uuids)),
    )
    return cursor.rowcount


def _mark_blocked(cursor: psycopg2.extensions.cursor, chunk: Chunk, person_uuids: Sequence[str]) -> list[str]:
    """Stamp the rows and return the uuids actually stamped."""
    if not person_uuids:
        return []
    # Same deleted_at guard as the delete: a row the sweep re-queued mid-flight belongs to a newer
    # tombstone, and stamping it blocked on this stale answer would park it for the retry window.
    cursor.execute(
        f"""
        UPDATE {PG_CLEANUP_QUEUE_TABLE}
        SET blocked_at = now()
        WHERE team_id = %s AND deleted_at = %s AND person_uuid = ANY(%s::uuid[])
        RETURNING person_uuid
        """,
        (chunk.team_id, chunk.deleted_at, list(person_uuids)),
    )
    return [str(person_uuid) for (person_uuid,) in cursor.fetchall()]


def _queue_rows_estimate(cursor: psycopg2.extensions.cursor) -> int:
    # Planner statistics, so this is free however large the queue grows; an exact count would
    # scan every pending row.
    cursor.execute("SELECT reltuples::bigint FROM pg_class WHERE oid = %s::regclass", (PG_CLEANUP_QUEUE_TABLE,))
    [[estimate]] = cursor.fetchall()
    return max(int(estimate), 0)


def _personhog_client() -> PersonHogClient:
    try:
        return require_personhog_client()
    except RuntimeError as exc:
        raise dagster.Failure(
            "personhog client is not configured: PERSONHOG_ADDR is unset in this pod, so the drain cannot delete"
        ) from exc


def _request_metadata(chunk: Chunk, sent: Sequence[str]) -> dict[str, dagster.MetadataValue]:
    return {
        "team_id": dagster.MetadataValue.int(chunk.team_id),
        "deleted_at": dagster.MetadataValue.text(chunk.deleted_at.isoformat()),
        "chunk_size": dagster.MetadataValue.int(len(chunk.person_uuids)),
        "sent_size": dagster.MetadataValue.int(len(sent)),
        "first_uuid": dagster.MetadataValue.text(sent[0]),
        "last_uuid": dagster.MetadataValue.text(sent[-1]),
    }


class _Drain:
    """One run's state: the personhog client, the Postgres session, the step size and the totals."""

    def __init__(
        self,
        context: dagster.OpExecutionContext,
        config: DrainConfig,
        metrics: MetricsClient,
        client: PersonHogClient | None,
        persons_database_url: str,
    ) -> None:
        self.context = context
        self.config = config
        self.metrics = metrics
        self.client = client
        self.persons_database_url = persons_database_url
        self.connection: psycopg2.extensions.connection | None = None
        self.totals = DrainTotals()
        self.step_rows = min(STEP_START_ROWS, config.max_rows_per_request)
        self.totals.step_rows_min = self.totals.step_rows_max = self.step_rows
        self.successes_at_step = 0
        self.deadline = math.inf if config.max_runtime_seconds == 0 else _now_monotonic() + config.max_runtime_seconds
        self.blocked_before = datetime.now(UTC) - timedelta(hours=config.blocked_retry_hours)

    def out_of_time(self) -> bool:
        if _now_monotonic() <= self.deadline:
            return False
        self.totals.stopped_reason = "max_runtime"
        return True

    def page_limit(self) -> int:
        if self.config.max_persons == 0:
            return self.config.page_size
        return min(self.config.page_size, self.config.max_persons - self.totals.rows_read)

    def close(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.close()
        except Exception:
            self.context.log.warning("closing the persons connection failed", exc_info=True)
        self.connection = None

    def timed_pg(self, fn: Callable[[psycopg2.extensions.cursor], _T]) -> _T:
        """Run one queue statement, retrying conflicts and reconnecting after a lost connection.

        Every statement is idempotent (a keyset read, a guarded delete, a guarded stamp), so running
        it again after a failure of unknown outcome is safe.
        """
        spent = 0.0
        failures = 0
        while True:
            started = time.perf_counter()
            try:
                if self.connection is None:
                    self.connection = _connect(self.persons_database_url)
                    if failures:
                        self.totals.pg_reconnects += 1
                with self.connection.cursor() as cursor:
                    result = fn(cursor)
            except psycopg2.Error as exc:
                elapsed = time.perf_counter() - started
                spent += elapsed
                self.totals.pg_seconds_total += elapsed
                failures += 1
                recovery = pg_recovery(exc)
                if recovery is None:
                    raise dagster.Failure(
                        f"persons Postgres statement failed: {exc}", metadata=self.totals.as_metadata()
                    ) from exc
                if spent >= self.config.pg_retry_window_seconds:
                    raise dagster.Failure(
                        f"persons Postgres kept failing for {spent:.0f}s over {failures} attempts: {exc}",
                        metadata=self.totals.as_metadata(),
                    ) from exc
                if recovery == "reconnect":
                    self.close()
                pause = backoff_seconds(PG_RETRY_BACKOFF_SECONDS, failures)
                self.context.log.warning(
                    "persons Postgres %s (%s); attempt %d in %.1fs",
                    "connection lost, reconnecting" if recovery == "reconnect" else "statement conflicted, retrying",
                    getattr(exc, "pgcode", None) or type(exc).__name__,
                    failures + 1,
                    pause,
                )
                _pause(pause)
                spent += pause
                continue
            self.totals.pg_seconds_total += time.perf_counter() - started
            return result

    def pages(self) -> Iterator[list[QueueRow]]:
        after: QueueCursor | None = None
        while not self.out_of_time():
            limit = self.page_limit()
            if limit <= 0:
                self.totals.stopped_reason = "max_persons"
                return
            read = partial(_read_page, after=after, limit=limit, blocked_before=self.blocked_before)
            page = self.timed_pg(read)
            if not page:
                return
            self.totals.rows_read += len(page)
            self.totals.pages += 1
            self.totals.teams_touched.update(row.team_id for row in page)
            yield page
            last = page[-1]
            after = QueueCursor(team_id=last.team_id, person_uuid=last.person_uuid)

    def send(self, chunk: Chunk, uuids: Sequence[str]) -> DeleteTombstonedPersonsResponse:
        """One personhog request, retried with backoff until it succeeds or the retry window passes.

        A timeout halves the row budget before the retry, so a step that outran the router's
        deadline is re-sent smaller; nothing is ever stamped or skipped because of a failed request.
        """
        assert self.client is not None
        client = self.client
        request = DeleteTombstonedPersonsRequest(team_id=chunk.team_id, person_uuids=list(uuids))
        spent = 0.0
        failures = 0
        while True:
            request.max_rows = self.step_rows
            started = time.perf_counter()
            try:
                response = personhog_call(
                    "delete_tombstoned_persons",
                    lambda: client.delete_tombstoned_persons(request, timeout=self.config.rpc_timeout_seconds),
                    caller_tag=PERSONHOG_CALLER_TAG,
                )
            except grpc.RpcError as exc:
                spent += time.perf_counter() - started
                code = _status_code(exc)
                failures += 1
                self.totals.rpc_errors += 1
                _emit(self.metrics, "person_pg_cleanup_drain_rpc_calls", {"result": "error", "code": _code_name(code)})
                if code == grpc.StatusCode.UNIMPLEMENTED:
                    # An older router or replica does not know the RPC. Failing here is the point:
                    # the legacy DeletePersons would hard-delete revived persons.
                    raise dagster.Failure(
                        "personhog does not serve DeleteTombstonedPersons yet; deploy personhog-router and "
                        "personhog-replica with it before running the drain",
                        metadata={**self.totals.as_metadata(), **_request_metadata(chunk, uuids)},
                    ) from exc
                if code in FATAL_RPC_CODES:
                    raise dagster.Failure(
                        f"personhog rejected the request with {_code_name(code)}; retrying cannot change that",
                        metadata={**self.totals.as_metadata(), **_request_metadata(chunk, uuids)},
                    ) from exc
                if code in SLOW_RPC_CODES:
                    self.shrink_step()
                if spent >= self.config.rpc_retry_window_seconds:
                    raise dagster.Failure(
                        f"personhog kept failing for {spent:.0f}s over {failures} attempts (last {_code_name(code)}); "
                        "the rows of this request stay queued for the next run",
                        metadata={
                            **self.totals.as_metadata(),
                            **_request_metadata(chunk, uuids),
                            "attempts": dagster.MetadataValue.int(failures),
                            "grpc_code": dagster.MetadataValue.text(_code_name(code)),
                        },
                    ) from exc
                pause = backoff_seconds(self.config.retry_backoff_seconds, failures)
                self.context.log.warning(
                    "personhog delete of %d persons failed (%s); attempt %d in %.1fs with a %d-row budget",
                    len(uuids),
                    _code_name(code),
                    failures + 1,
                    pause,
                    self.step_rows,
                )
                _pause(pause)
                spent += pause
                continue
            self.totals.rpc_calls += 1
            self.totals.rpc_seconds.append(time.perf_counter() - started)
            self.grow_step()
            return response

    def shrink_step(self) -> None:
        self.step_rows = max(STEP_FLOOR_ROWS, self.step_rows // 2)
        self.successes_at_step = 0
        self.totals.step_rows_min = min(self.totals.step_rows_min, self.step_rows)

    def grow_step(self) -> None:
        self.successes_at_step += 1
        if self.successes_at_step < STEP_GROWTH_SUCCESSES:
            return
        self.step_rows = min(self.step_rows * 2, self.config.max_rows_per_request)
        self.successes_at_step = 0
        self.totals.step_rows_max = max(self.totals.step_rows_max, self.step_rows)

    def resolve(self, chunk: Chunk) -> None:
        """Send the chunk, then send its pending persons again until personhog has resolved every one."""
        self.totals.chunks += 1
        pending: Sequence[str] = chunk.person_uuids
        while pending:
            if self.out_of_time():
                # Rows of the persons still pending stay queued; the next run continues them.
                return
            response = self.send(chunk, pending)
            self.apply(chunk, pending, response)
            _pause(pause_seconds(self.config.pause_ms, self.config.latency_multiplier, self.totals.rpc_seconds[-1]))
            pending = list(response.pending_person_uuids)
            if pending:
                self.totals.requests_pending_resent += 1

    def apply(self, chunk: Chunk, sent: Sequence[str], response: DeleteTombstonedPersonsResponse) -> None:
        blocked = sorted(response.blocked_person_uuids)
        unresolved = set(blocked) | set(response.pending_person_uuids)
        resolved = [uuid for uuid in sent if uuid not in unresolved]
        # Skipped-live rows go too: the queue row is stale, and the sweep queues the person again
        # if it is ever tombstoned again.
        self.totals.persons_deleted += response.deleted_count
        self.totals.persons_skipped_live += response.skipped_live_count
        self.totals.persons_not_found += len(resolved) - response.deleted_count - response.skipped_live_count
        self.totals.persons_blocked += len(blocked)
        self.totals.rows_deleted += response.rows_deleted
        self.totals.queue_rows_deleted += self.timed_pg(lambda cursor: _delete_queue_rows(cursor, chunk, resolved))
        if blocked:
            self.stamp_blocked(chunk, blocked)

    def stamp_blocked(self, chunk: Chunk, uuids: Sequence[str]) -> None:
        stamped = self.timed_pg(lambda cursor: _mark_blocked(cursor, chunk, list(uuids)))
        self.totals.rows_stamped_blocked += len(stamped)
        room = max(0, BLOCKED_SAMPLE_SIZE - len(self.totals.blocked_sample))
        self.totals.blocked_sample.extend(stamped[:room])
        if self.totals.rows_stamped_blocked <= self.config.max_blocked:
            return
        raise dagster.Failure(
            f"{self.totals.rows_stamped_blocked} queue rows stamped blocked_at this run (tombstoned persons that "
            f"still own a live distinct id), more than max_blocked={self.config.max_blocked}; this needs "
            "investigation, not more retries",
            metadata={**self.totals.as_metadata(), **_request_metadata(chunk, uuids)},
        )

    def emit_counters_since(self, before: DrainTotals) -> None:
        after = self.totals
        for outcome, delta in (
            ("deleted", after.persons_deleted - before.persons_deleted),
            ("skipped_live", after.persons_skipped_live - before.persons_skipped_live),
            ("not_found", after.persons_not_found - before.persons_not_found),
            ("blocked", after.persons_blocked - before.persons_blocked),
        ):
            _emit(self.metrics, "person_pg_cleanup_drain_persons", {"outcome": outcome}, delta)
        _emit(self.metrics, "person_pg_cleanup_drain_rows_deleted", {}, after.rows_deleted - before.rows_deleted)
        _emit(
            self.metrics,
            "person_pg_cleanup_drain_queue_rows_deleted",
            {},
            after.queue_rows_deleted - before.queue_rows_deleted,
        )
        _emit(
            self.metrics,
            "person_pg_cleanup_drain_rpc_calls",
            {"result": "ok", "code": "OK"},
            after.rpc_calls - before.rpc_calls,
        )
        _emit(self.metrics, "person_pg_cleanup_drain_pg_reconnects", {}, after.pg_reconnects - before.pg_reconnects)

    def snapshot(self) -> DrainTotals:
        return DrainTotals(
            persons_deleted=self.totals.persons_deleted,
            persons_skipped_live=self.totals.persons_skipped_live,
            persons_not_found=self.totals.persons_not_found,
            persons_blocked=self.totals.persons_blocked,
            rows_deleted=self.totals.rows_deleted,
            queue_rows_deleted=self.totals.queue_rows_deleted,
            rpc_calls=self.totals.rpc_calls,
            pg_reconnects=self.totals.pg_reconnects,
        )

    def run(self) -> DrainTotals:
        self.totals.queue_rows_estimate_at_start = self.timed_pg(_queue_rows_estimate)
        # Counters flush every LOG_EVERY_PAGES pages and once on the way out, success or failure:
        # per-page inserts would be tens of thousands of tiny ClickHouse inserts on a large queue.
        emitted = self.snapshot()
        try:
            for page in self.pages():
                if self.config.dry_run:
                    continue
                for chunk in chunks_for_page(page, self.config.rpc_batch_size):
                    self.resolve(chunk)
                    if self.totals.stopped_reason == "max_runtime":
                        break
                if self.totals.pages % LOG_EVERY_PAGES == 0:
                    self.emit_counters_since(emitted)
                    emitted = self.snapshot()
                    self.log_progress()
                if self.totals.stopped_reason == "max_runtime":
                    # Requests left in this page were never sent, so their rows stay queued.
                    break
        except Exception:
            self.totals.stopped_reason = "failed"
            raise
        finally:
            self.emit_counters_since(emitted)
        return self.totals

    def log_progress(self) -> None:
        totals = self.totals
        self.context.log.info(
            "%d pages, %d rows: deleted=%d skipped_live=%d not_found=%d blocked=%d rows_deleted=%d, "
            "%d pending re-sends, step %d rows (%d..%d), rpc p50 %.3fs, %d rpc errors, %d pg reconnects",
            totals.pages,
            totals.rows_read,
            totals.persons_deleted,
            totals.persons_skipped_live,
            totals.persons_not_found,
            totals.persons_blocked,
            totals.rows_deleted,
            totals.requests_pending_resent,
            self.step_rows,
            totals.step_rows_min,
            totals.step_rows_max,
            statistics.median(totals.rpc_seconds) if totals.rpc_seconds else 0.0,
            totals.rpc_errors,
            totals.pg_reconnects,
        )


@dagster.op
def drain_person_pg_cleanup_queue(
    context: dagster.OpExecutionContext,
    config: DrainConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    persons_database_url: dagster.ResourceParam[str],
) -> DrainTotals:
    """Page the queue by primary key, delete each batch through personhog, remove the resolved rows.

    A dry run pages and counts only: it never resolves the personhog client and never writes.
    """
    # Resolved before Postgres is dialed, so a pod without PERSONHOG_ADDR fails before it
    # touches the persons writer.
    client = None if config.dry_run else _personhog_client()

    metrics = MetricsClient(cluster)
    drain = _Drain(context, config, metrics, client, persons_database_url)
    try:
        totals = drain.run()
    finally:
        drain.close()
        drain.log_progress()
        _emit(
            metrics,
            "person_pg_cleanup_drain_runs",
            {"stopped_reason": drain.totals.stopped_reason, "dry_run": str(config.dry_run).lower()},
        )

    context.add_output_metadata({**totals.as_metadata(), "dry_run": dagster.MetadataValue.bool(config.dry_run)})
    return totals


@dagster.job(
    tags={
        "owner": JobOwners.TEAM_INGESTION.value,
        # The sweep's run-queue tag (limit 1 in charts argocd/dagster/deployment_settings), so a
        # drain never runs alongside a sweep or another drain.
        "clickhouse_deletion_sweep_concurrency": "v1",
    },
    executor_def=dagster.in_process_executor,
)
def person_pg_cleanup_drain_job():
    """Hard-delete the Postgres rows of persons the ClickHouse sweep has already removed."""
    drain_person_pg_cleanup_queue()
