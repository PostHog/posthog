"""Drain person_pg_cleanup_queue into Postgres hard deletes.

The ClickHouse sweep (clickhouse_cleanup.py) removes a deleted person's rows from ClickHouse and
queues the person here. Postgres still holds the tombstoned posthog_person row and its
posthog_persondistinctid rows until this job asks personhog to delete them.

The queue is advisory. A person can be revived in Postgres after it was queued, so the job never
deletes on the queue's word: it hands each batch to personhog's DeleteTombstonedPersons, which
deletes a person only while it is still tombstoned, under row locks, and reports the rest back.
Queue rows are removed once personhog has resolved the person either way. Rows personhog could
not resolve (a tombstoned person that still owns a live distinct id) are stamped blocked_at and
skipped for a retry interval.

One run pod, sequential batches, every statement and RPC bounded, and a pause after each RPC so
the persons writer never sees a burst.
"""

import time
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TypeVar

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

# personhog-replica runs each delete chunk under this statement timeout. A client deadline below
# it would abandon a delete the server keeps running, then retry it on top.
REPLICA_CHUNK_STATEMENT_TIMEOUT_SECONDS = 30.0

RETRY_BACKOFF_CAP_SECONDS = 60.0
LOG_EVERY_PAGES = 10
BLOCKED_SAMPLE_SIZE = 50

_T = TypeVar("_T")


class DrainConfig(dagster.Config):
    dry_run: bool = pydantic.Field(
        default=True,
        description="Page and count the queue without calling personhog or writing to Postgres.",
    )
    max_persons: int = pydantic.Field(
        default=100_000,
        description="Stop after reading this many queue rows, 0 for no cap. A capped run leaves the rest for the "
        "next run.",
    )
    page_size: int = pydantic.Field(default=1000, description="Queue rows per Postgres read, at most 1000.")
    rpc_batch_size: int = pydantic.Field(
        default=200,
        description="Person uuids per personhog request, at most 1000. The replica deletes in chunks of 100, so "
        "200 keeps each request at two chunk transactions on the persons writer.",
    )
    pause_ms: int = pydantic.Field(default=200, description="Pause after every personhog request.")
    latency_multiplier: float = pydantic.Field(
        default=1.0,
        description="Extra pause after every request, as a multiple of that request's latency. When the persons "
        "writer slows down, the drain slows down with it.",
    )
    rpc_timeout_seconds: float = pydantic.Field(
        default=60.0,
        description="Deadline per personhog request. Must exceed the replica's 30 s chunk statement timeout.",
    )
    max_runtime_seconds: int = pydantic.Field(
        default=4 * 3600,
        description="Stop taking new pages and chunks after this many seconds, then finish cleanly.",
    )
    max_consecutive_failures: int = pydantic.Field(
        default=5, description="Failed personhog attempts in a row before the run fails."
    )
    retry_backoff_seconds: float = pydantic.Field(
        default=2.0, description="Pause after the first failed attempt. Doubles per attempt, capped at 60 s."
    )
    blocked_retry_hours: int = pydantic.Field(
        default=24, description="Skip rows personhog reported blocked more recently than this."
    )
    max_blocked: int = pydantic.Field(
        default=1000,
        description="Fail the run once more rows than this come back blocked. A tombstoned person that still owns "
        "a live distinct id is an ingestion invariant violation, and that many of them needs a person, not a retry.",
    )

    @pydantic.model_validator(mode="after")
    def validate_bounds(self) -> "DrainConfig":
        if not 1 <= self.page_size <= RPC_MAX_UUIDS:
            raise ValueError(f"page_size must be between 1 and {RPC_MAX_UUIDS}")
        if not 1 <= self.rpc_batch_size <= RPC_MAX_UUIDS:
            raise ValueError(f"rpc_batch_size must be between 1 and {RPC_MAX_UUIDS}")
        if self.rpc_timeout_seconds <= REPLICA_CHUNK_STATEMENT_TIMEOUT_SECONDS:
            raise ValueError(
                f"rpc_timeout_seconds must exceed the replica's {REPLICA_CHUNK_STATEMENT_TIMEOUT_SECONDS:.0f} s "
                "chunk statement timeout"
            )
        if self.max_persons < 0 or self.pause_ms < 0 or self.latency_multiplier < 0 or self.blocked_retry_hours < 0:
            raise ValueError("max_persons, pause_ms, latency_multiplier and blocked_retry_hours must not be negative")
        if self.max_runtime_seconds <= 0 or self.max_consecutive_failures <= 0:
            raise ValueError("max_runtime_seconds and max_consecutive_failures must be positive")
        if self.retry_backoff_seconds < 0 or self.max_blocked < 0:
            raise ValueError("retry_backoff_seconds and max_blocked must not be negative")
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
    persons_deleted: int = 0
    persons_skipped_live: int = 0
    persons_not_found: int = 0
    persons_blocked: int = 0
    blocked_sample: list[str] = field(default_factory=list)
    queue_rows_deleted: int = 0
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
            "persons_deleted": dagster.MetadataValue.int(self.persons_deleted),
            "persons_skipped_live": dagster.MetadataValue.int(self.persons_skipped_live),
            "persons_not_found": dagster.MetadataValue.int(self.persons_not_found),
            "persons_blocked": dagster.MetadataValue.int(self.persons_blocked),
            "blocked_sample": dagster.MetadataValue.text(", ".join(self.blocked_sample) or "none"),
            "queue_rows_deleted": dagster.MetadataValue.int(self.queue_rows_deleted),
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


def is_retryable_pg_error(exc: BaseException) -> bool:
    # Serialization failure and deadlock: the statement can simply run again.
    return isinstance(exc, psycopg2.Error) and getattr(exc, "pgcode", None) in {"40001", "40P01"}


def pause_seconds(pause_ms: int, latency_multiplier: float, last_rpc_seconds: float) -> float:
    return pause_ms / 1000.0 + latency_multiplier * last_rpc_seconds


def _status_code(exc: grpc.RpcError) -> grpc.StatusCode | None:
    code = getattr(exc, "code", None)
    return code() if callable(code) else None


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


def _mark_blocked(cursor: psycopg2.extensions.cursor, chunk: Chunk, person_uuids: Sequence[str]) -> None:
    if not person_uuids:
        return
    cursor.execute(
        f"UPDATE {PG_CLEANUP_QUEUE_TABLE} SET blocked_at = now() WHERE team_id = %s AND person_uuid = ANY(%s::uuid[])",
        (chunk.team_id, list(person_uuids)),
    )


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


def _chunk_metadata(chunk: Chunk) -> dict[str, dagster.MetadataValue]:
    return {
        "team_id": dagster.MetadataValue.int(chunk.team_id),
        "deleted_at": dagster.MetadataValue.text(chunk.deleted_at.isoformat()),
        "chunk_size": dagster.MetadataValue.int(len(chunk.person_uuids)),
        "first_uuid": dagster.MetadataValue.text(chunk.person_uuids[0]),
        "last_uuid": dagster.MetadataValue.text(chunk.person_uuids[-1]),
    }


class _Drain:
    """One run's state: the personhog client, the Postgres session and the running totals."""

    def __init__(
        self,
        context: dagster.OpExecutionContext,
        config: DrainConfig,
        metrics: MetricsClient,
        client: PersonHogClient | None,
        connection: psycopg2.extensions.connection,
    ) -> None:
        self.context = context
        self.config = config
        self.metrics = metrics
        self.client = client
        self.connection = connection
        self.totals = DrainTotals()
        self.deadline = _now_monotonic() + config.max_runtime_seconds
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

    def timed_pg(self, fn: Callable[[psycopg2.extensions.cursor], _T]) -> _T:
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                with self.connection.cursor() as cursor:
                    return fn(cursor)
            except psycopg2.Error as exc:
                attempt += 1
                if not is_retryable_pg_error(exc) or attempt >= self.config.max_consecutive_failures:
                    raise dagster.Failure(
                        f"persons Postgres statement failed: {exc}", metadata=self.totals.as_metadata()
                    ) from exc
                self.context.log.warning("Postgres statement conflicted (%s), retrying", getattr(exc, "pgcode", "?"))
                _pause(1.0)
            finally:
                self.totals.pg_seconds_total += time.perf_counter() - started

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

    def send_with_retry(self, chunk: Chunk) -> DeleteTombstonedPersonsResponse:
        assert self.client is not None
        client = self.client
        request = DeleteTombstonedPersonsRequest(team_id=chunk.team_id, person_uuids=list(chunk.person_uuids))
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                response = personhog_call(
                    "delete_tombstoned_persons",
                    lambda: client.delete_tombstoned_persons(request, timeout=self.config.rpc_timeout_seconds),
                    caller_tag=PERSONHOG_CALLER_TAG,
                )
            except grpc.RpcError as exc:
                self.totals.rpc_errors += 1
                code = _status_code(exc)
                _emit(
                    self.metrics,
                    "person_pg_cleanup_drain_rpc_calls",
                    {"result": "error", "code": code.name if code else "unknown"},
                )
                if code == grpc.StatusCode.UNIMPLEMENTED:
                    # An older router or replica does not know the RPC. Failing here is the point:
                    # the legacy DeletePersons would hard-delete revived persons.
                    raise dagster.Failure(
                        "personhog does not serve DeleteTombstonedPersons yet; deploy personhog-router and "
                        "personhog-replica with it before running the drain",
                        metadata={**self.totals.as_metadata(), **_chunk_metadata(chunk)},
                    ) from exc
                attempt += 1
                if attempt >= self.config.max_consecutive_failures:
                    raise dagster.Failure(
                        f"personhog DeleteTombstonedPersons failed {attempt} times in a row ({code})",
                        metadata={
                            **self.totals.as_metadata(),
                            **_chunk_metadata(chunk),
                            "attempts": dagster.MetadataValue.int(attempt),
                            "grpc_code": dagster.MetadataValue.text(code.name if code else "unknown"),
                        },
                    ) from exc
                backoff = min(self.config.retry_backoff_seconds * 2 ** (attempt - 1), RETRY_BACKOFF_CAP_SECONDS)
                self.context.log.warning(
                    "personhog delete failed (%s); attempt %d of %d, retrying in %.1fs",
                    code,
                    attempt,
                    self.config.max_consecutive_failures,
                    backoff,
                )
                _pause(backoff)
                continue
            self.totals.rpc_calls += 1
            self.totals.rpc_seconds.append(time.perf_counter() - started)
            return response

    def drain_chunk(self, chunk: Chunk) -> None:
        response = self.send_with_retry(chunk)
        blocked = set(response.blocked_person_uuids)
        resolved = [uuid for uuid in chunk.person_uuids if uuid not in blocked]
        # Skipped-live rows go too. Postgres sees that person alive, so the queue row is stale;
        # if the person is tombstoned again the sweep queues it again. Left in place, live rows
        # would accumulate and eat every run's budget.
        self.totals.persons_deleted += response.deleted_count
        self.totals.persons_skipped_live += response.skipped_live_count
        self.totals.persons_not_found += len(resolved) - response.deleted_count - response.skipped_live_count
        self.totals.persons_blocked += len(blocked)
        self.totals.blocked_sample.extend(
            sorted(blocked)[: max(0, BLOCKED_SAMPLE_SIZE - len(self.totals.blocked_sample))]
        )
        self.totals.chunks += 1
        self.totals.queue_rows_deleted += self.timed_pg(lambda cursor: _delete_queue_rows(cursor, chunk, resolved))
        if blocked:
            self.timed_pg(lambda cursor: _mark_blocked(cursor, chunk, sorted(blocked)))
        if self.totals.persons_blocked > self.config.max_blocked:
            raise dagster.Failure(
                f"{self.totals.persons_blocked} queued persons are tombstoned but still own a live distinct id, "
                f"more than max_blocked={self.config.max_blocked}; this needs investigation, not more retries",
                metadata={**self.totals.as_metadata(), **_chunk_metadata(chunk)},
            )
        _pause(pause_seconds(self.config.pause_ms, self.config.latency_multiplier, self.totals.rpc_seconds[-1]))

    def emit_counters_since(self, before: DrainTotals) -> None:
        after = self.totals
        for outcome, delta in (
            ("deleted", after.persons_deleted - before.persons_deleted),
            ("skipped_live", after.persons_skipped_live - before.persons_skipped_live),
            ("not_found", after.persons_not_found - before.persons_not_found),
            ("blocked", after.persons_blocked - before.persons_blocked),
        ):
            _emit(self.metrics, "person_pg_cleanup_drain_persons", {"outcome": outcome}, delta)
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

    def snapshot(self) -> DrainTotals:
        return DrainTotals(
            persons_deleted=self.totals.persons_deleted,
            persons_skipped_live=self.totals.persons_skipped_live,
            persons_not_found=self.totals.persons_not_found,
            persons_blocked=self.totals.persons_blocked,
            queue_rows_deleted=self.totals.queue_rows_deleted,
            rpc_calls=self.totals.rpc_calls,
        )

    def run(self) -> DrainTotals:
        self.totals.queue_rows_estimate_at_start = self.timed_pg(_queue_rows_estimate)
        # Counters flush every LOG_EVERY_PAGES pages and once at the end: one ClickHouse insert per
        # counter per page would be tens of thousands of tiny inserts on a large queue.
        emitted = self.snapshot()
        for page in self.pages():
            if self.config.dry_run:
                continue
            for chunk in chunks_for_page(page, self.config.rpc_batch_size):
                if self.out_of_time():
                    break
                self.drain_chunk(chunk)
            if self.totals.pages % LOG_EVERY_PAGES == 0:
                self.emit_counters_since(emitted)
                emitted = self.snapshot()
                self.log_progress()
            if self.totals.stopped_reason == "max_runtime":
                # Chunks left in this page were never sent, so their rows stay queued.
                break
        self.emit_counters_since(emitted)
        return self.totals

    def log_progress(self) -> None:
        totals = self.totals
        self.context.log.info(
            "%d pages, %d rows: deleted=%d skipped_live=%d not_found=%d blocked=%d, rpc p50 %.3fs, %d rpc errors",
            totals.pages,
            totals.rows_read,
            totals.persons_deleted,
            totals.persons_skipped_live,
            totals.persons_not_found,
            totals.persons_blocked,
            statistics.median(totals.rpc_seconds) if totals.rpc_seconds else 0.0,
            totals.rpc_errors,
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

    # Connected inside the op and in autocommit: one statement per transaction, so no
    # transaction stays open on the persons writer across a personhog call or a pause.
    connection = psycopg2.connect(persons_database_url, connect_timeout=10)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET application_name = %s", (PG_APPLICATION_NAME,))
            cursor.execute("SET statement_timeout = '30s'")
            cursor.execute("SET lock_timeout = '5s'")
        drain = _Drain(context, config, MetricsClient(cluster), client, connection)
        totals = drain.run()
    finally:
        connection.close()

    drain.log_progress()
    _emit(
        MetricsClient(cluster),
        "person_pg_cleanup_drain_runs",
        {"stopped_reason": totals.stopped_reason, "dry_run": str(config.dry_run).lower()},
    )
    context.add_output_metadata({**totals.as_metadata(), "dry_run": dagster.MetadataValue.bool(config.dry_run)})
    return totals


@dagster.job(tags={"owner": JobOwners.TEAM_INGESTION.value}, executor_def=dagster.in_process_executor)
def person_pg_cleanup_drain_job():
    """Hard-delete the Postgres rows of persons the ClickHouse sweep has already removed."""
    drain_person_pg_cleanup_queue()
