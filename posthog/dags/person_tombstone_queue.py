import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import field
from functools import partial
from typing import TypeVar
from uuid import UUID

import dagster
from prometheus_client import Gauge

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.kafka_client.routing import flush_all_producers
from posthog.metrics import pushed_metrics_registry
from posthog.models.person.tombstone_log import (
    PendingPersonTombstone,
    TombstoneConsumer,
    ack_person_tombstones_for_consumer,
    list_pending_person_tombstones,
    list_person_tombstone_distinct_ids,
    retire_acked_person_tombstones,
)
from posthog.models.person.util import (
    DistinctIdForPerson,
    PersonTombstone,
    QueuedPersonTombstone,
    ack_person_tombstones,
    get_person_tombstones,
    list_person_tombstone_queue,
    publish_person_tombstone,
)

METRICS_JOB = "person_tombstone_queue"
PAGE_SIZE = 1000
CHUNK_SIZE = 100
FLUSH_TIMEOUT_SECONDS = 60
# A team's pass is retried before the team is given up on. The sweep runs weekly, so a team that
# stays broken waits for the next run rather than holding the whole queue.
TEAM_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5
# Caps keep one run's memory and time bounded however large the backlog grows.
LOG_HEADER_PAGE_SIZE = 100
MAX_LOG_ENTRIES_PER_RUN = 1000
MAX_LOG_SCANNED_PER_RUN = 10 * MAX_LOG_ENTRIES_PER_RUN
# Where the next run resumes its scan, per team range. Each run moves past what it attempted, so
# entries that keep failing at the front cannot keep later generations from ever being tried. The
# scan wraps to the start once it reaches the end, and failed entries are retried on the next pass.
PUBLICATION_LOG_CURSOR_KEY = "person_tombstone_queue.publication_log_after"
LOG_IDENTITY_PAGE_SIZE = CHUNK_SIZE
MAX_RETIRE_CALLS = 200

_T = TypeVar("_T")


@frozen(frozen=False)
class QueueResolution:
    listed: int = 0
    dropped: int = 0
    confirmed: int = 0
    republished: int = 0
    # Teams whose queue could not be resolved after TEAM_ATTEMPTS. Their rows stay queued and count
    # as remaining.
    failed_teams: int = 0
    remaining: list[QueuedPersonTombstone] = field(default_factory=list)
    log_listed: int = 0
    log_skipped_out_of_range: int = 0
    log_confirmed: int = 0
    log_republished: int = 0
    log_retired: int = 0
    log_failed_entries: int = 0
    log_more_pending: bool = False
    # None restarts the next run from the oldest entry.
    log_next_after: int | None = None
    log_unavailable: bool = False
    log_remaining: list[PendingPersonTombstone] = field(default_factory=list)


@frozen
class _TeamPass:
    dropped: int
    confirmed: int
    pending: dict[UUID, PersonTombstone]


def _with_retries(fn: Callable[[], _T]) -> _T:
    for attempt in range(TEAM_ATTEMPTS):
        try:
            return fn()
        except Exception:
            if attempt == TEAM_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * 2**attempt)
    raise AssertionError("unreachable")


def _in_range(team_id: int, min_team_id: int, max_team_id: int) -> bool:
    return (not min_team_id or team_id >= min_team_id) and (not max_team_id or team_id <= max_team_id)


def _list_queue(min_team_id: int, max_team_id: int) -> list[QueuedPersonTombstone]:
    rows: list[QueuedPersonTombstone] = []
    after: tuple[int, UUID] | None = None
    while page := list_person_tombstone_queue(after, PAGE_SIZE):
        rows.extend(row for row in page if _in_range(row.team_id, min_team_id, max_team_id))
        after = (page[-1].team_id, page[-1].person_uuid)
    return rows


def _is_shown(row: tuple[int, int] | None, version: int) -> bool:
    # A missing row is not confirmation: the live row can still be in flight through Kafka, and
    # acking now would leave nothing queued to delete it when it lands.
    if row is None:
        return False
    is_deleted, max_version = row
    return max_version > version or (bool(is_deleted) and max_version >= version)


def clickhouse_confirmed(team_id: int, tombstones: Sequence[PersonTombstone]) -> set[UUID]:
    if not tombstones:
        return set()
    persons = {
        str(person_id): (is_deleted, max_version)
        for person_id, is_deleted, max_version in sync_execute(
            """
            SELECT id, argMax(is_deleted, version), max(version)
            FROM person
            WHERE team_id = %(team_id)s AND id IN %(ids)s
            GROUP BY id
            """,
            {"team_id": team_id, "ids": [str(t.uuid) for t in tombstones]},
        )
    }
    distinct_ids = [d.id for t in tombstones for d in t.distinct_ids]
    mappings = (
        {
            distinct_id: (is_deleted, max_version)
            for distinct_id, is_deleted, max_version in sync_execute(
                """
                SELECT distinct_id, argMax(is_deleted, version), max(version)
                FROM person_distinct_id2
                WHERE team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s
                GROUP BY distinct_id
                """,
                {"team_id": team_id, "distinct_ids": distinct_ids},
            )
        }
        if distinct_ids
        else {}
    )
    return {
        t.uuid
        for t in tombstones
        if _is_shown(persons.get(str(t.uuid)), t.version)
        and all(_is_shown(mappings.get(d.id), d.version) for d in t.distinct_ids)
    }


def _confirm_and_ack(team_id: int, tombstones: dict[UUID, PersonTombstone]) -> int:
    """Ack the queued persons ClickHouse shows as deleted, a chunk at a time, and drop them from ``tombstones``."""
    batch = list(tombstones.values())
    acked = 0
    for i in range(0, len(batch), CHUNK_SIZE):
        confirmed = clickhouse_confirmed(team_id, batch[i : i + CHUNK_SIZE])
        if not confirmed:
            continue
        ack_person_tombstones(team_id, [(uuid, tombstones[uuid].version) for uuid in confirmed])
        acked += len(confirmed)
        for uuid in confirmed:
            del tombstones[uuid]
    return acked


def _resolve_team(team_id: int, team_rows: Sequence[QueuedPersonTombstone], *, dry_run: bool) -> _TeamPass:
    """Ack the rows ClickHouse already shows as deleted, or that no longer exist, and return the rest.

    Acks as it goes, so a retry after a failed chunk re-confirms the acked rows without harm: the
    ack is idempotent, and the counts come from this pass alone.
    """
    dropped = confirmed_count = 0
    pending: dict[UUID, PersonTombstone] = {}
    for i in range(0, len(team_rows), CHUNK_SIZE):
        chunk = team_rows[i : i + CHUNK_SIZE]
        stored = {t.uuid: t for t in get_person_tombstones(team_id, [row.person_uuid for row in chunk])}
        gone = [(row.person_uuid, row.person_version) for row in chunk if row.person_uuid not in stored]
        confirmed = clickhouse_confirmed(team_id, list(stored.values()))
        dropped += len(gone)
        confirmed_count += len(confirmed)
        if not dry_run:
            ack_person_tombstones(team_id, gone + [(uuid, stored[uuid].version) for uuid in confirmed])
        for uuid, tombstone in stored.items():
            if uuid not in confirmed:
                pending[uuid] = tombstone
    return _TeamPass(dropped=dropped, confirmed=confirmed_count, pending=pending)


def resolve_person_tombstone_queue(
    *,
    dry_run: bool,
    min_team_id: int,
    max_team_id: int,
    visibility_timeout_seconds: int,
    poll_interval_seconds: int,
    log: Callable[[str], None],
    log_after: int | None = None,
) -> QueueResolution:
    """Resolve every queued tombstone in the team range, one team at a time.

    The shared tombstone log is resolved after the legacy queue, starting after ``log_after``.
    Pass the previous run's ``log_next_after`` so the scan keeps moving through the log.

    A team whose pass keeps failing is logged, counted in ``failed_teams`` and left queued for the
    next run. No single failure stops the other teams or the sweep that runs after this.
    """
    result = QueueResolution()
    queued = _list_queue(min_team_id, max_team_id)
    result.listed = len(queued)
    by_team: dict[int, list[QueuedPersonTombstone]] = defaultdict(list)
    for row in queued:
        by_team[row.team_id].append(row)

    pending: dict[int, dict[UUID, PersonTombstone]] = {}
    failed: list[QueuedPersonTombstone] = []
    row_for: dict[tuple[int, UUID], QueuedPersonTombstone] = {(row.team_id, row.person_uuid): row for row in queued}
    for team_id, team_rows in by_team.items():
        try:
            team_pass = _with_retries(partial(_resolve_team, team_id, team_rows, dry_run=dry_run))
        except Exception as exc:
            log(
                f"team {team_id}: resolving its tombstone queue failed {TEAM_ATTEMPTS} times: {type(exc).__name__}: {exc}"
            )
            result.failed_teams += 1
            failed.extend(team_rows)
            continue
        result.dropped += team_pass.dropped
        result.confirmed += team_pass.confirmed
        if team_pass.pending:
            pending[team_id] = team_pass.pending

    if dry_run:
        result.republished = sum(len(p) for p in pending.values())
        result.remaining = [row_for[(team_id, uuid)] for team_id, p in pending.items() for uuid in p] + failed
        _resolve_publication_log(
            result,
            dry_run=True,
            min_team_id=min_team_id,
            max_team_id=max_team_id,
            visibility_timeout_seconds=visibility_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            log=log,
            after=log_after,
        )
        return result

    for team_id, tombstones in pending.items():
        for tombstone in tombstones.values():
            try:
                publish_person_tombstone(team_id, tombstone)
                result.republished += 1
            except Exception as exc:
                log(f"publishing the tombstone for person {tombstone.uuid} failed: {type(exc).__name__}: {exc}")
    undelivered = flush_all_producers(FLUSH_TIMEOUT_SECONDS)
    if undelivered:
        log(f"{undelivered} Kafka messages were not delivered")

    deadline = time.monotonic() + visibility_timeout_seconds
    while True:
        for team_id in list(pending):
            try:
                result.confirmed += _with_retries(partial(_confirm_and_ack, team_id, pending[team_id]))
            except Exception as exc:
                log(
                    f"team {team_id}: confirming its republished tombstones failed {TEAM_ATTEMPTS} times: {type(exc).__name__}: {exc}"
                )
                result.failed_teams += 1
                failed.extend(row_for[(team_id, uuid)] for uuid in pending.pop(team_id))
                continue
            if not pending[team_id]:
                del pending[team_id]
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(poll_interval_seconds)

    result.remaining = [
        row_for[(team_id, uuid)] for team_id, tombstones in pending.items() for uuid in tombstones
    ] + failed
    _resolve_publication_log(
        result,
        dry_run=dry_run,
        min_team_id=min_team_id,
        max_team_id=max_team_id,
        visibility_timeout_seconds=visibility_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        log=log,
        after=log_after,
    )
    return result


def _pending_log_entries(
    result: QueueResolution, min_team_id: int, max_team_id: int, after: int | None
) -> list[PendingPersonTombstone]:
    only_team = min_team_id if min_team_id and min_team_id == max_team_id else None
    entries: list[PendingPersonTombstone] = []
    scanned = 0
    last_scanned = after
    cursor = after
    while True:
        page = list_pending_person_tombstones(
            TombstoneConsumer.PUBLICATION, after=cursor, limit=LOG_HEADER_PAGE_SIZE, team_id=only_team
        )
        for entry in page.entries:
            if len(entries) == MAX_LOG_ENTRIES_PER_RUN or scanned == MAX_LOG_SCANNED_PER_RUN:
                result.log_more_pending = True
                result.log_next_after = last_scanned
                return entries
            scanned += 1
            last_scanned = entry.log_id
            if _in_range(entry.team_id, min_team_id, max_team_id):
                entries.append(entry)
            else:
                result.log_skipped_out_of_range += 1
        if page.next_cursor is None:
            result.log_next_after = None
            return entries
        cursor = page.next_cursor


def _publication_log_cursor_key(min_team_id: int, max_team_id: int) -> str:
    return f"{PUBLICATION_LOG_CURSOR_KEY}:{min_team_id}:{max_team_id}"


def load_publication_log_cursor(instance: dagster.DagsterInstance, min_team_id: int, max_team_id: int) -> int | None:
    key = _publication_log_cursor_key(min_team_id, max_team_id)
    value = instance.run_storage.get_cursor_values({key}).get(key)
    return int(value) if value else None


def store_publication_log_cursor(
    instance: dagster.DagsterInstance, min_team_id: int, max_team_id: int, after: int | None
) -> None:
    key = _publication_log_cursor_key(min_team_id, max_team_id)
    instance.run_storage.set_cursor_values({key: "" if after is None else str(after)})


def _identity_chunks(entry: PendingPersonTombstone) -> Iterator[PersonTombstone]:
    after_id = 0
    first = True
    while True:
        page = list_person_tombstone_distinct_ids(
            entry.team_id, entry.log_id, after_id=after_id, limit=LOG_IDENTITY_PAGE_SIZE
        )
        if page.identities or first:
            yield PersonTombstone(
                uuid=entry.person_uuid,
                version=entry.person_version,
                distinct_ids=[DistinctIdForPerson(id=row.distinct_id, version=row.version) for row in page.identities],
                log_id=entry.log_id,
            )
        first = False
        if page.next_cursor is None:
            return
        after_id = page.next_cursor


def _entry_confirmed(entry: PendingPersonTombstone, *, publish: bool) -> bool:
    confirmed = True
    for chunk in _identity_chunks(entry):
        if clickhouse_confirmed(entry.team_id, [chunk]):
            continue
        confirmed = False
        if not publish:
            return False
        publish_person_tombstone(entry.team_id, chunk)
    return confirmed


def _ack_entry_publication(entry: PendingPersonTombstone) -> None:
    ack_person_tombstones_for_consumer(TombstoneConsumer.PUBLICATION, entry.team_id, [entry.log_id])


def _log_failure(log: Callable[[str], None], entry: PendingPersonTombstone, step: str, exc: Exception) -> None:
    # Exception text can carry the distinct ids being published, so only its type is logged.
    log(f"tombstone log entry {entry.log_id} of team {entry.team_id}: {step} failed: {type(exc).__name__}")


def _resolve_publication_log(
    result: QueueResolution,
    *,
    dry_run: bool,
    min_team_id: int,
    max_team_id: int,
    visibility_timeout_seconds: int,
    poll_interval_seconds: int,
    log: Callable[[str], None],
    after: int | None = None,
) -> None:
    """The log entry outlives the legacy queue row and the person rows, so this still works after both are gone.

    An entry is acked by its exact log id, and only once ClickHouse shows every page of its distinct ids.
    """
    try:
        entries = _pending_log_entries(result, min_team_id, max_team_id, after)
    except Exception as exc:
        result.log_unavailable = True
        result.log_next_after = after
        log(f"reading the shared tombstone log failed: {type(exc).__name__}")
        return
    result.log_listed = len(entries)

    republished: list[PendingPersonTombstone] = []
    for entry in entries:
        try:
            if _with_retries(partial(_entry_confirmed, entry, publish=False)):
                if not dry_run:
                    _with_retries(partial(_ack_entry_publication, entry))
                result.log_confirmed += 1
                continue
            if dry_run:
                result.log_republished += 1
                result.log_remaining.append(entry)
                continue
            _with_retries(partial(_entry_confirmed, entry, publish=True))
        except Exception as exc:
            _log_failure(log, entry, "publishing", exc)
            result.log_failed_entries += 1
            result.log_remaining.append(entry)
            continue
        result.log_republished += 1
        republished.append(entry)

    if dry_run:
        return
    undelivered = flush_all_producers(FLUSH_TIMEOUT_SECONDS)
    if undelivered:
        log(f"{undelivered} Kafka messages were not delivered")

    deadline = time.monotonic() + visibility_timeout_seconds
    while republished:
        still_pending: list[PendingPersonTombstone] = []
        for entry in republished:
            try:
                if _with_retries(partial(_entry_confirmed, entry, publish=False)):
                    _with_retries(partial(_ack_entry_publication, entry))
                    result.log_confirmed += 1
                else:
                    still_pending.append(entry)
            except Exception as exc:
                _log_failure(log, entry, "confirming", exc)
                result.log_failed_entries += 1
                result.log_remaining.append(entry)
        republished = still_pending
        if not republished or time.monotonic() >= deadline:
            break
        time.sleep(poll_interval_seconds)
    result.log_remaining.extend(republished)

    try:
        for _ in range(MAX_RETIRE_CALLS):
            retirement = retire_acked_person_tombstones()
            result.log_retired += retirement.retired
            if not retirement.has_more:
                break
    except Exception as exc:
        log(f"retiring acked tombstone log entries failed: {type(exc).__name__}")


def publish_queue_gauges(result: QueueResolution, completed_at: float) -> None:
    """Publish what the run measured. Only a completed run reaches here: a run that could not list
    the queue publishes nothing, so a staleness alert on the last-run gauge is what reports it."""
    oldest_ms = min((row.tombstoned_at_ms for row in result.remaining), default=None)
    with pushed_metrics_registry(METRICS_JOB) as registry:
        Gauge(
            "posthog_person_tombstone_queue_listed_rows",
            "Queued persons the weekly repair read in its team range",
            registry=registry,
        ).set(result.listed)
        Gauge(
            "posthog_person_tombstone_queue_dropped_rows",
            "Queued persons acked because the persons DB no longer holds their tombstone: revived or hard-deleted. Counts team passes that completed",
            registry=registry,
        ).set(result.dropped)
        Gauge(
            "posthog_person_tombstone_queue_confirmed_rows",
            "Queued persons acked because ClickHouse shows their tombstone, before or after a republish. Counts team passes that completed; a failed team's rows are in unresolved_rows",
            registry=registry,
        ).set(result.confirmed)
        Gauge(
            "posthog_person_tombstone_queue_republished_rows",
            "Queued persons whose tombstone the weekly repair produced again at the stored versions, in team passes that completed; confirmed_rows says how many then showed in ClickHouse",
            registry=registry,
        ).set(result.republished)
        Gauge(
            "posthog_person_tombstone_queue_unresolved_rows",
            "Queued persons the weekly repair could not confirm in ClickHouse: deleted in Postgres, possibly live in ClickHouse",
            registry=registry,
        ).set(len(result.remaining))
        Gauge(
            "posthog_person_tombstone_queue_failed_teams",
            "Teams whose queue the weekly repair gave up on after retries; their rows stay queued",
            registry=registry,
        ).set(result.failed_teams)
        Gauge(
            "posthog_person_tombstone_queue_oldest_unresolved_seconds",
            "Age of the oldest queued person the weekly repair could not confirm",
            registry=registry,
        ).set(completed_at - oldest_ms / 1000 if oldest_ms is not None else 0)
        Gauge(
            "posthog_person_tombstone_log_publication_listed_entries",
            "Shared tombstone log entries the weekly repair read that publication had not acked",
            registry=registry,
        ).set(result.log_listed)
        Gauge(
            "posthog_person_tombstone_log_publication_unresolved_entries",
            "Shared tombstone log entries the weekly repair could not confirm in ClickHouse; they stay pending",
            registry=registry,
        ).set(len(result.log_remaining))
        Gauge(
            "posthog_person_tombstone_log_publication_more_pending",
            "1 when the weekly repair stopped at its per-run cap before the end of the log; the next run resumes after it",
            registry=registry,
        ).set(1 if result.log_more_pending else 0)
        Gauge(
            "posthog_person_tombstone_log_unavailable",
            "1 when the weekly repair could not read the shared tombstone log at all",
            registry=registry,
        ).set(1 if result.log_unavailable else 0)
        Gauge(
            "posthog_person_tombstone_queue_last_run_timestamp_seconds",
            "Unix time when the weekly repair last finished",
            registry=registry,
        ).set(completed_at)
