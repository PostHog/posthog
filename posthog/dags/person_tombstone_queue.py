import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import field
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


@frozen(frozen=False)
class QueueResolution:
    listed: int = 0
    dropped: int = 0
    confirmed: int = 0
    republished: int = 0
    remaining: list[QueuedPersonTombstone] = field(default_factory=list)


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
    if row is None:
        return True
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


def resolve_person_tombstone_queue(
    *,
    dry_run: bool,
    min_team_id: int,
    max_team_id: int,
    visibility_timeout_seconds: int,
    poll_interval_seconds: int,
    log: Callable[[str], None],
) -> QueueResolution:
    result = QueueResolution()
    queued = _list_queue(min_team_id, max_team_id)
    result.listed = len(queued)
    by_team: dict[int, list[QueuedPersonTombstone]] = defaultdict(list)
    for row in queued:
        by_team[row.team_id].append(row)

    pending: dict[int, dict[UUID, PersonTombstone]] = defaultdict(dict)
    row_for: dict[UUID, QueuedPersonTombstone] = {row.person_uuid: row for row in queued}
    for team_id, team_rows in by_team.items():
        for i in range(0, len(team_rows), CHUNK_SIZE):
            chunk = team_rows[i : i + CHUNK_SIZE]
            stored = {t.uuid: t for t in get_person_tombstones(team_id, [row.person_uuid for row in chunk])}
            gone = [(row.person_uuid, row.person_version) for row in chunk if row.person_uuid not in stored]
            confirmed = clickhouse_confirmed(team_id, list(stored.values()))
            result.dropped += len(gone)
            result.confirmed += len(confirmed)
            if not dry_run:
                ack_person_tombstones(team_id, gone + [(uuid, stored[uuid].version) for uuid in confirmed])
            for uuid, tombstone in stored.items():
                if uuid not in confirmed:
                    pending[team_id][uuid] = tombstone

    if dry_run:
        result.republished = sum(len(p) for p in pending.values())
        result.remaining = [row_for[uuid] for p in pending.values() for uuid in p]
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
            tombstones = pending[team_id]
            confirmed = clickhouse_confirmed(team_id, list(tombstones.values()))
            if confirmed:
                ack_person_tombstones(team_id, [(uuid, tombstones[uuid].version) for uuid in confirmed])
                result.confirmed += len(confirmed)
                for uuid in confirmed:
                    del tombstones[uuid]
            if not tombstones:
                del pending[team_id]
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(poll_interval_seconds)

    result.remaining = [row_for[uuid] for tombstones in pending.values() for uuid in tombstones]
    return result


def publish_queue_gauges(result: QueueResolution, completed_at: float) -> None:
    oldest_ms = min((row.tombstoned_at_ms for row in result.remaining), default=None)
    with pushed_metrics_registry(METRICS_JOB) as registry:
        Gauge(
            "posthog_person_tombstone_queue_unresolved_rows",
            "Queued persons the weekly repair could not confirm in ClickHouse: deleted in Postgres, possibly live in ClickHouse",
            registry=registry,
        ).set(len(result.remaining))
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
