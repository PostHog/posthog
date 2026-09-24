import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import field
from functools import partial
from typing import TypeVar
from uuid import UUID

from prometheus_client import Gauge

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.kafka_client.routing import flush_all_producers
from posthog.metrics import pushed_metrics_registry
from posthog.models.person.util import (
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
) -> QueueResolution:
    """Resolve every queued tombstone in the team range, one team at a time.

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
    return result


def publish_queue_gauges(result: QueueResolution, completed_at: float) -> None:
    """Publish what the run measured. Only a completed run reaches here: a run that could not list
    the queue publishes nothing, so a staleness alert on the last-run gauge is what reports it."""
    oldest_ms = min((row.tombstoned_at_ms for row in result.remaining), default=None)
    with pushed_metrics_registry(METRICS_JOB) as registry:
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
            "posthog_person_tombstone_queue_last_run_timestamp_seconds",
            "Unix time when the weekly repair last finished",
            registry=registry,
        ).set(completed_at)
