"""Drain person_pg_cleanup_queue into Postgres hard deletes.

The ClickHouse sweep (clickhouse_cleanup.py) removes a deleted person's rows from ClickHouse and
queues the person here. Postgres still holds the tombstoned posthog_person row and its
posthog_persondistinctid rows until this job asks personhog to delete them.

The queue is advisory. A person can be revived in Postgres after it was queued, so the job never
deletes on the queue's word: it hands each batch to personhog's DeleteTombstonedPersons, which
deletes a person only while it is still tombstoned, under row locks, and reports the rest back.
Queue rows are removed once personhog has resolved the person either way. A person with more
dependent rows (distinct ids, hash key overrides, cohort memberships) than one delete transaction
may touch is trimmed first, one bounded TrimTombstonedPerson step at a time, then deleted. Rows
personhog could not resolve are stamped blocked_at and skipped for a retry interval: a tombstoned
person that still owns a live distinct id, or a person whose requests kept failing.

One run pod, sequential requests, every statement and RPC bounded, and a pause after each RPC so
the persons writer never sees a burst. A request that fails is split in half and retried, so one
slow or broken person costs its own row, not the run. Run time is the variable that gives: a
person of any size is deleted in steps that each fit the deadline, and the run keeps going until
the queue is drained or max_runtime_seconds passes.
"""

import time
import statistics
from collections import defaultdict, deque
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
from posthog.personhog_client.proto import (
    DeleteTombstonedPersonsRequest,
    DeleteTombstonedPersonsResponse,
    TrimTombstonedPersonRequest,
    TrimTombstonedPersonResponse,
)

logger = dagster.get_dagster_logger(__name__)

PERSONHOG_CALLER_TAG = "clickhouse_cleanup/person-pg-drain"
PG_APPLICATION_NAME = "person_pg_cleanup_drain"

# Server-side cap on DeleteTombstonedPersonsRequest.person_uuids.
RPC_MAX_UUIDS = 1000

# personhog-router gives every backend call this long (BACKEND_TIMEOUT_MS) and takes the shorter
# of it and the client deadline. The replica deletes a request in chunks of REPLICA_CHUNK_SIZE
# uuids (the production BULK_CHUNK_SIZE), one transaction each.
ROUTER_BACKEND_TIMEOUT_SECONDS = 5.0
REPLICA_CHUNK_SIZE = 100

# personhog-replica clamps a trim step to TOMBSTONED_TRIM_MAX_ROWS; the config bound mirrors it.
TRIM_MAX_ROWS = 10_000

RETRY_BACKOFF_CAP_SECONDS = 60.0
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
        description="Person uuids per personhog request, at most 1000. 100 is one replica chunk, which production "
        "deletes well inside the router's 5 s budget per backend call. A request that fails is split in half and "
        "retried, down to one person.",
    )
    pause_ms: int = pydantic.Field(default=200, description="Pause after every personhog request.")
    latency_multiplier: float = pydantic.Field(
        default=1.0,
        description="Extra pause after every request, as a multiple of that request's latency. When the persons "
        "writer slows down, the drain slows down with it.",
    )
    rpc_timeout_seconds: float = pydantic.Field(
        default=ROUTER_BACKEND_TIMEOUT_SECONDS,
        description="Deadline per personhog request. personhog-router caps every backend call at 5 s, so a longer "
        "deadline only waits on the router's own retries of the same call.",
    )
    trim_batch_rows: int = pydantic.Field(
        default=5000,
        description="Dependent rows deleted per TrimTombstonedPerson step while a person is over the replica's cap, "
        f"at most {TRIM_MAX_ROWS}. The replica clamps it to its own maximum.",
    )
    max_runtime_seconds: int = pydantic.Field(
        default=12 * 3600,
        description="Stop taking new pages, requests and trim steps after this many seconds, then finish cleanly. "
        "Rows left over wait for the next run; trimmed rows stay deleted.",
    )
    max_consecutive_failures: int = pydantic.Field(
        default=5,
        description="Failed personhog attempts in a row, across requests, before the run fails. One person that "
        "keeps failing is isolated by splitting and stamped blocked_at, which does not trip this; an outage does.",
    )
    max_attempts_per_person: int = pydantic.Field(
        default=3,
        description="Attempts for a single-person request before its row is stamped blocked_at and the run moves on.",
    )
    retry_backoff_seconds: float = pydantic.Field(
        default=2.0,
        description="Pause before the retry after a failed attempt. Doubles per consecutive failure, capped at 60 s, "
        "resets on success.",
    )
    blocked_retry_hours: int = pydantic.Field(
        default=24, description="Skip rows stamped blocked_at more recently than this."
    )
    max_blocked: int = pydantic.Field(
        default=1000,
        description="Fail the run once more rows than this are stamped blocked_at in one run: a tombstoned person "
        "that still owns a live distinct id, a person over the replica's distinct-id cap, or a request that kept "
        "failing. That many needs a person, not a retry.",
    )

    @pydantic.model_validator(mode="after")
    def validate_bounds(self) -> "DrainConfig":
        if not 1 <= self.page_size <= RPC_MAX_UUIDS:
            raise ValueError(f"page_size must be between 1 and {RPC_MAX_UUIDS}")
        if not 1 <= self.rpc_batch_size <= RPC_MAX_UUIDS:
            raise ValueError(f"rpc_batch_size must be between 1 and {RPC_MAX_UUIDS}")
        if self.rpc_timeout_seconds <= 0:
            raise ValueError("rpc_timeout_seconds must be positive")
        if not 1 <= self.trim_batch_rows <= TRIM_MAX_ROWS:
            raise ValueError(f"trim_batch_rows must be between 1 and {TRIM_MAX_ROWS}")
        if self.max_persons < 0 or self.pause_ms < 0 or self.latency_multiplier < 0 or self.blocked_retry_hours < 0:
            raise ValueError("max_persons, pause_ms, latency_multiplier and blocked_retry_hours must not be negative")
        if self.max_runtime_seconds <= 0 or self.max_consecutive_failures <= 0 or self.max_attempts_per_person <= 0:
            raise ValueError(
                "max_runtime_seconds, max_consecutive_failures and max_attempts_per_person must be positive"
            )
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

    def halves(self) -> list["Chunk"]:
        middle = len(self.person_uuids) // 2
        return [
            Chunk(team_id=self.team_id, deleted_at=self.deleted_at, person_uuids=self.person_uuids[:middle]),
            Chunk(team_id=self.team_id, deleted_at=self.deleted_at, person_uuids=self.person_uuids[middle:]),
        ]


@frozen(frozen=False)
class DrainTotals:
    rows_read: int = 0
    pages: int = 0
    chunks: int = 0
    rpc_calls: int = 0
    rpc_errors: int = 0
    rpc_splits: int = 0
    persons_deleted: int = 0
    persons_skipped_live: int = 0
    persons_not_found: int = 0
    persons_blocked: int = 0
    persons_oversized: int = 0
    persons_trimmed: int = 0
    persons_rpc_failed: int = 0
    trim_calls: int = 0
    rows_trimmed: int = 0
    rows_stamped_blocked: int = 0
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
            "rpc_splits": dagster.MetadataValue.int(self.rpc_splits),
            "persons_deleted": dagster.MetadataValue.int(self.persons_deleted),
            "persons_skipped_live": dagster.MetadataValue.int(self.persons_skipped_live),
            "persons_not_found": dagster.MetadataValue.int(self.persons_not_found),
            "persons_blocked": dagster.MetadataValue.int(self.persons_blocked),
            "persons_oversized": dagster.MetadataValue.int(self.persons_oversized),
            "persons_trimmed": dagster.MetadataValue.int(self.persons_trimmed),
            "persons_rpc_failed": dagster.MetadataValue.int(self.persons_rpc_failed),
            "trim_calls": dagster.MetadataValue.int(self.trim_calls),
            "rows_trimmed": dagster.MetadataValue.int(self.rows_trimmed),
            "rows_stamped_blocked": dagster.MetadataValue.int(self.rows_stamped_blocked),
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


class _AttemptFailed(Exception):
    """One personhog attempt failed with a code another attempt may clear."""

    def __init__(self, code: grpc.StatusCode | None) -> None:
        super().__init__(code)
        self.code = code


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
    # Serialization failure, deadlock, lock_timeout and statement_timeout: the statement can
    # simply run again.
    return isinstance(exc, psycopg2.Error) and getattr(exc, "pgcode", None) in {"40001", "40P01", "55P03", "57014"}


def pause_seconds(pause_ms: int, latency_multiplier: float, last_rpc_seconds: float) -> float:
    return pause_ms / 1000.0 + latency_multiplier * last_rpc_seconds


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
    # Same deleted_at guard as the delete: a row the sweep re-queued mid-flight belongs to a newer
    # tombstone, and stamping it blocked on this stale answer would park it for the retry window.
    cursor.execute(
        f"""
        UPDATE {PG_CLEANUP_QUEUE_TABLE}
        SET blocked_at = now()
        WHERE team_id = %s AND deleted_at = %s AND person_uuid = ANY(%s::uuid[])
        """,
        (chunk.team_id, chunk.deleted_at, list(person_uuids)),
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
        self.consecutive_failures = 0
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
                    result = fn(cursor)
            except psycopg2.Error as exc:
                self.totals.pg_seconds_total += time.perf_counter() - started
                attempt += 1
                if not is_retryable_pg_error(exc) or attempt >= self.config.max_consecutive_failures:
                    raise dagster.Failure(
                        f"persons Postgres statement failed: {exc}", metadata=self.totals.as_metadata()
                    ) from exc
                self.context.log.warning("Postgres statement conflicted (%s), retrying", getattr(exc, "pgcode", "?"))
                _pause(1.0)
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

    def send(self, chunk: Chunk) -> DeleteTombstonedPersonsResponse:
        assert self.client is not None
        client = self.client
        request = DeleteTombstonedPersonsRequest(team_id=chunk.team_id, person_uuids=list(chunk.person_uuids))
        return self.attempt(
            chunk,
            "delete_tombstoned_persons",
            lambda: client.delete_tombstoned_persons(request, timeout=self.config.rpc_timeout_seconds),
        )

    def send_trim(self, chunk: Chunk) -> TrimTombstonedPersonResponse:
        assert self.client is not None
        client = self.client
        [uuid] = chunk.person_uuids
        request = TrimTombstonedPersonRequest(
            team_id=chunk.team_id, person_uuid=uuid, max_rows=self.config.trim_batch_rows
        )
        return self.attempt(
            chunk,
            "trim_tombstoned_person",
            lambda: client.trim_tombstoned_person(request, timeout=self.config.rpc_timeout_seconds),
        )

    def attempt(self, chunk: Chunk, method: str, invoke: Callable[[], _T]) -> _T:
        """One personhog attempt. Fatal codes and an outage fail the run; anything else is retryable."""
        started = time.perf_counter()
        try:
            response = personhog_call(method, invoke, caller_tag=PERSONHOG_CALLER_TAG)
        except grpc.RpcError as exc:
            code = _status_code(exc)
            self.totals.rpc_errors += 1
            self.consecutive_failures += 1
            _emit(self.metrics, "person_pg_cleanup_drain_rpc_calls", {"result": "error", "code": _code_name(code)})
            if code == grpc.StatusCode.UNIMPLEMENTED:
                # An older router or replica does not know the RPC. Failing here is the point:
                # the legacy DeletePersons would hard-delete revived persons.
                raise dagster.Failure(
                    f"personhog does not serve {method} yet; deploy personhog-router and personhog-replica "
                    "with it before running the drain",
                    metadata={**self.totals.as_metadata(), **_chunk_metadata(chunk)},
                ) from exc
            if code in FATAL_RPC_CODES:
                raise dagster.Failure(
                    f"personhog rejected {method} with {_code_name(code)}; retrying cannot change that",
                    metadata={**self.totals.as_metadata(), **_chunk_metadata(chunk)},
                ) from exc
            if self.consecutive_failures >= self.config.max_consecutive_failures:
                raise dagster.Failure(
                    f"personhog {method} failed {self.consecutive_failures} times in a row ({_code_name(code)})",
                    metadata={
                        **self.totals.as_metadata(),
                        **_chunk_metadata(chunk),
                        "attempts": dagster.MetadataValue.int(self.consecutive_failures),
                        "grpc_code": dagster.MetadataValue.text(_code_name(code)),
                    },
                ) from exc
            raise _AttemptFailed(code) from exc
        self.consecutive_failures = 0
        self.totals.rpc_calls += 1
        self.totals.rpc_seconds.append(time.perf_counter() - started)
        return response

    def backoff(self, chunk: Chunk, code: grpc.StatusCode | None) -> None:
        pause = min(self.config.retry_backoff_seconds * 2 ** (self.consecutive_failures - 1), RETRY_BACKOFF_CAP_SECONDS)
        self.context.log.warning(
            "personhog delete of %d persons failed (%s); %d failures in a row, next attempt in %.1fs",
            len(chunk.person_uuids),
            _code_name(code),
            self.consecutive_failures,
            pause,
        )
        _pause(pause)

    def resolve(self, chunk: Chunk, trim_oversized: bool = True) -> None:
        """Send the chunk, splitting a failed request in half until each person is resolved or given up.

        Halves go to the back of the queue, so a single broken person never produces a long run
        of failures and the outage detector in attempt() stays meaningful.
        """
        pending: deque[tuple[Chunk, int]] = deque([(chunk, 0)])
        while pending and not self.out_of_time():
            current, attempts = pending.popleft()
            try:
                response = self.send(current)
            except _AttemptFailed as failed:
                self.backoff(current, failed.code)
                if len(current.person_uuids) > 1:
                    self.totals.rpc_splits += 1
                    pending.extend((half, 0) for half in current.halves())
                elif attempts + 1 < self.config.max_attempts_per_person:
                    pending.append((current, attempts + 1))
                else:
                    self.give_up(current, failed.code)
                continue
            self.apply(current, response, trim_oversized)

    def give_up(self, chunk: Chunk, code: grpc.StatusCode | None) -> None:
        [uuid] = chunk.person_uuids
        self.context.log.warning(
            "personhog could not resolve person %s of team %d after %d attempts (%s); stamping its row blocked_at",
            uuid,
            chunk.team_id,
            self.config.max_attempts_per_person,
            _code_name(code),
        )
        self.totals.chunks += 1
        self.totals.persons_rpc_failed += 1
        self.stamp_blocked(chunk, "rpc_failed", [uuid])

    def apply(self, chunk: Chunk, response: DeleteTombstonedPersonsResponse, trim_oversized: bool) -> None:
        blocked = sorted(response.blocked_person_uuids)
        oversized = sorted(response.oversized_person_uuids)
        unresolved = set(blocked) | set(oversized)
        resolved = [uuid for uuid in chunk.person_uuids if uuid not in unresolved]
        # Skipped-live rows go too. Postgres sees that person alive, so the queue row is stale;
        # if the person is tombstoned again the sweep queues it again. Left in place, live rows
        # would accumulate and eat every run's budget.
        self.totals.persons_deleted += response.deleted_count
        self.totals.persons_skipped_live += response.skipped_live_count
        self.totals.persons_not_found += len(resolved) - response.deleted_count - response.skipped_live_count
        self.totals.persons_blocked += len(blocked)
        self.totals.persons_oversized += len(oversized)
        self.totals.chunks += 1
        self.totals.queue_rows_deleted += self.timed_pg(lambda cursor: _delete_queue_rows(cursor, chunk, resolved))
        if blocked:
            self.stamp_blocked(chunk, "live_distinct_id", blocked)
        _pause(pause_seconds(self.config.pause_ms, self.config.latency_multiplier, self.totals.rpc_seconds[-1]))
        for uuid in oversized:
            if trim_oversized:
                self.trim_then_delete(chunk, uuid)
            else:
                # A person that is still over the cap right after trimming under it has grown
                # again, which no tombstoned person does. Park it where operators can see it.
                self.stamp_blocked(chunk, "oversized", [uuid])

    def trim_then_delete(self, chunk: Chunk, uuid: str) -> None:
        """Take one oversized person under the cap a bounded step at a time, then delete it.

        Every step is one short replica transaction and is committed on its own, so a run that
        ends mid-way loses nothing: the row stays queued and the next run continues from there.
        """
        single = Chunk(team_id=chunk.team_id, deleted_at=chunk.deleted_at, person_uuids=(uuid,))
        attempts = 0
        while not self.out_of_time():
            try:
                step = self.send_trim(single)
            except _AttemptFailed as failed:
                self.backoff(single, failed.code)
                attempts += 1
                if attempts >= self.config.max_attempts_per_person:
                    self.give_up(single, failed.code)
                return_reason = "gave_up" if attempts >= self.config.max_attempts_per_person else None
                if return_reason:
                    return
                continue
            attempts = 0
            deleted = step.distinct_ids_deleted + step.hash_key_overrides_deleted + step.cohort_memberships_deleted
            self.totals.trim_calls += 1
            self.totals.rows_trimmed += deleted
            _pause(pause_seconds(self.config.pause_ms, self.config.latency_multiplier, self.totals.rpc_seconds[-1]))
            if not step.person_tombstoned or not step.over_cap:
                self.totals.persons_trimmed += 1
                self.resolve(single, trim_oversized=False)
                return
            if deleted == 0:
                # Over the cap with nothing left to trim: the remaining rows are live distinct
                # ids, so the person is blocked, not oversized.
                self.totals.persons_blocked += 1
                self.totals.chunks += 1
                self.stamp_blocked(single, "live_distinct_id", [uuid])
                return

    def stamp_blocked(self, chunk: Chunk, reason: str, uuids: Sequence[str]) -> None:
        self.totals.rows_stamped_blocked += len(uuids)
        room = max(0, BLOCKED_SAMPLE_SIZE - len(self.totals.blocked_sample))
        self.totals.blocked_sample.extend(f"{reason}:{uuid}" for uuid in list(uuids)[:room])
        self.timed_pg(lambda cursor: _mark_blocked(cursor, chunk, list(uuids)))
        self.check_blocked_budget(chunk)

    def check_blocked_budget(self, chunk: Chunk) -> None:
        totals = self.totals
        if totals.rows_stamped_blocked <= self.config.max_blocked:
            return
        raise dagster.Failure(
            f"{totals.rows_stamped_blocked} queue rows stamped blocked_at this run "
            f"({totals.persons_blocked} with a live distinct id, {totals.persons_rpc_failed} with failing "
            f"requests), more than max_blocked={self.config.max_blocked}; this needs investigation, not more retries",
            metadata={**totals.as_metadata(), **_chunk_metadata(chunk)},
        )

    def emit_counters_since(self, before: DrainTotals) -> None:
        after = self.totals
        for outcome, delta in (
            ("deleted", after.persons_deleted - before.persons_deleted),
            ("skipped_live", after.persons_skipped_live - before.persons_skipped_live),
            ("not_found", after.persons_not_found - before.persons_not_found),
            ("blocked", after.persons_blocked - before.persons_blocked),
            ("oversized", after.persons_oversized - before.persons_oversized),
            ("trimmed", after.persons_trimmed - before.persons_trimmed),
            ("rpc_failed", after.persons_rpc_failed - before.persons_rpc_failed),
        ):
            _emit(self.metrics, "person_pg_cleanup_drain_persons", {"outcome": outcome}, delta)
        _emit(self.metrics, "person_pg_cleanup_drain_trim_calls", {}, after.trim_calls - before.trim_calls)
        _emit(self.metrics, "person_pg_cleanup_drain_rows_trimmed", {}, after.rows_trimmed - before.rows_trimmed)
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
            persons_oversized=self.totals.persons_oversized,
            persons_trimmed=self.totals.persons_trimmed,
            persons_rpc_failed=self.totals.persons_rpc_failed,
            trim_calls=self.totals.trim_calls,
            rows_trimmed=self.totals.rows_trimmed,
            queue_rows_deleted=self.totals.queue_rows_deleted,
            rpc_calls=self.totals.rpc_calls,
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
                    if self.out_of_time():
                        break
                    self.resolve(chunk)
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
            "%d pages, %d rows: deleted=%d skipped_live=%d not_found=%d blocked=%d oversized=%d trimmed=%d "
            "(%d steps, %d rows) rpc_failed=%d, rpc p50 %.3fs, %d rpc errors, %d splits",
            totals.pages,
            totals.rows_read,
            totals.persons_deleted,
            totals.persons_skipped_live,
            totals.persons_not_found,
            totals.persons_blocked,
            totals.persons_oversized,
            totals.persons_trimmed,
            totals.trim_calls,
            totals.rows_trimmed,
            totals.persons_rpc_failed,
            statistics.median(totals.rpc_seconds) if totals.rpc_seconds else 0.0,
            totals.rpc_errors,
            totals.rpc_splits,
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
    metrics = MetricsClient(cluster)
    drain = _Drain(context, config, metrics, client, connection)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET application_name = %s", (PG_APPLICATION_NAME,))
            cursor.execute("SET statement_timeout = '30s'")
            cursor.execute("SET lock_timeout = '5s'")
        totals = drain.run()
    finally:
        connection.close()
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
        # The sweep's run-queue tag, limited to one run at a time in charts
        # (argocd/dagster/deployment_settings). Sharing it keeps a drain from running alongside a
        # sweep or another drain: both write the queue and both load the persons writer.
        "clickhouse_deletion_sweep_concurrency": "v1",
    },
    executor_def=dagster.in_process_executor,
)
def person_pg_cleanup_drain_job():
    """Hard-delete the Postgres rows of persons the ClickHouse sweep has already removed."""
    drain_person_pg_cleanup_queue()
