import datetime as dt
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.models.person.util import (
    PERSONHOG_BATCH_SIZE,
    PersonTombstone,
    PersonTombstonePublication,
    PersonVersionFloor,
    VersionFloorOutcome,
    ensure_person_version_floors,
    get_person_tombstones,
    get_persons_by_uuids,
)

logger = structlog.get_logger(__name__)

# personhog clamps uuid lookups at 250 per request; batch to match.
_PERSONHOG_UUID_BATCH = 250


# ── Orphaned ClickHouse person repair ────────────────────────────────
#
# A person can be hard-deleted from the persons DB (posthog_person + posthog_persondistinctid) with no matching
# ClickHouse tombstone. The row then stays visible to every ClickHouse-backed
# read path (HogQL `persons`, the UI Persons page) while every persons-DB write
# path 404s. This produces the missing tombstones so ClickHouse agrees with the
# persons DB.


@dataclass
class OrphanedPerson:
    """A ClickHouse person row that is live in CH but absent from the persons DB."""

    uuid: str
    ch_max_version: int
    created_at: dt.datetime


@dataclass
class _Mapping:
    """The current ClickHouse winner for a distinct_id (ReplacingMergeTree argMax)."""

    distinct_id: str
    winner_person_id: str
    winner_is_deleted: bool
    max_version: int


@dataclass(frozen=False)
class OrphanRepairResult:
    orphaned_person_uuids: list[str]
    # Orphans with no persons-DB row, which get a new persons-DB tombstone above ClickHouse.
    tombstoned_persons: int = 0
    # Orphans that are tombstoned in the persons DB, raised above ClickHouse when needed and republished.
    republished_persons: int = 0
    # Orphans the persons-DB primary holds as live, which a lagging replica read reported as missing.
    skipped_live_persons: int = 0
    # (distinct_id, winner_uuid) pairs where the CH mapping is tombstoned but the
    # winning person is live in the persons DB — the opposite drift, handled by
    # person_divergence repair, reported here rather than repaired.
    reverse_drift_mappings: list[tuple[str, str]] = field(default_factory=list)
    dry_run: bool = False


# Past this share of live ClickHouse persons missing from the persons DB, the team likely needs a restore.
ORPHAN_TOMBSTONE_SHARE_LIMIT = 0.05


def count_live_ch_persons(team_id: int) -> int:
    rows = sync_execute(
        """
            SELECT count() FROM (
                SELECT id FROM person WHERE team_id = %(team_id)s GROUP BY id HAVING argMax(is_deleted, version) = 0
            )
        """,
        {"team_id": team_id},
    )
    return int(rows[0][0])


def orphan_share_refusal(team_id: int, to_tombstone: int, live_ch_persons: int) -> Optional[str]:
    """Return why tombstoning this many ClickHouse-only persons is refused, or None when it is within the limit."""
    if to_tombstone <= ORPHAN_TOMBSTONE_SHARE_LIMIT * live_ch_persons:
        return None
    return (
        f"Refusing to tombstone {to_tombstone} of the {live_ch_persons} live ClickHouse persons of team {team_id}, "
        f"more than {ORPHAN_TOMBSTONE_SHARE_LIMIT:.0%}. A team whose persons-DB persons were lost, for example by "
        "an interrupted project deletion, needs a restore, and tombstoning destroys the ClickHouse copy the restore "
        "reads from. Pass --force only if these persons should really be deleted."
    )


def find_orphaned_ch_persons(team_id: int, uuids: Optional[list[str]] = None) -> list[OrphanedPerson]:
    """Return ClickHouse person rows that are live in CH but have no persons-DB row.

    With ``uuids`` set the search is scoped to those ids (a one-shot repair);
    otherwise every live CH person for the team is checked, which is a full scan.
    """
    candidates = _ch_live_persons(team_id, uuids)
    if not candidates:
        return []

    present_in_db: set[str] = set()
    candidate_uuids = list(candidates)
    for start in range(0, len(candidate_uuids), _PERSONHOG_UUID_BATCH):
        batch = candidate_uuids[start : start + _PERSONHOG_UUID_BATCH]
        present_in_db.update(str(p.uuid) for p in get_persons_by_uuids(team_id, batch, distinct_id_limit=0))

    return [
        OrphanedPerson(uuid=uuid, ch_max_version=max_version, created_at=created_at)
        for uuid, (max_version, created_at) in candidates.items()
        if uuid not in present_in_db
    ]


def tombstone_orphaned_ch_persons(
    team_id: int, orphans: list[OrphanedPerson], *, dry_run: bool = True
) -> OrphanRepairResult:
    """Tombstone orphaned persons in the persons DB one version above ClickHouse, then publish those tombstones.

    Each ClickHouse tombstone carries the exact stored version, so a later revival lands above it and a rerun
    republishes the same versions. Distinct ids get no tombstone of their own, because the ClickHouse deletion
    sweep removes every live mapping of a person it deletes.
    """
    result = OrphanRepairResult(orphaned_person_uuids=sorted(o.uuid for o in orphans), dry_run=dry_run)
    if not orphans:
        return result

    orphan_uuids = {o.uuid for o in orphans}
    deleted_winners = [m for m in _ch_mappings_for_persons(team_id, orphan_uuids) if m.winner_is_deleted]
    result.reverse_drift_mappings = _find_reverse_drift(team_id, deleted_winners, orphan_uuids)

    stored_by_uuid = {str(t.uuid): t for t in get_person_tombstones(team_id, [UUID(o.uuid) for o in orphans])}
    if dry_run:
        result.republished_persons = sum(1 for o in orphans if o.uuid in stored_by_uuid)
        result.tombstoned_persons = len(orphans) - result.republished_persons
        return result

    created_at_by_uuid = {o.uuid: o.created_at for o in orphans}
    floors = [PersonVersionFloor(uuid=UUID(o.uuid), min_version=o.ch_max_version + 1) for o in orphans]
    publication = PersonTombstonePublication(team_id=team_id, source="orphan_repair")
    try:
        # Each batch commits on its own, so it is published before the next batch starts, and a later failure
        # leaves no committed tombstone unpublished.
        for i in range(0, len(floors), PERSONHOG_BATCH_SIZE):
            to_publish: list[tuple[PersonTombstone, Optional[dt.datetime]]] = []
            for floor in ensure_person_version_floors(team_id, floors[i : i + PERSONHOG_BATCH_SIZE]):
                uuid = str(floor.uuid)
                if floor.outcome == VersionFloorOutcome.LIVE:
                    result.skipped_live_persons += 1
                    continue
                stored = stored_by_uuid.get(uuid)
                if stored is None:
                    result.tombstoned_persons += 1
                else:
                    result.republished_persons += 1
                tombstone = PersonTombstone(
                    uuid=floor.uuid, version=floor.version, distinct_ids=stored.distinct_ids if stored else []
                )
                to_publish.append((tombstone, created_at_by_uuid[uuid]))
            publication.publish(to_publish)
    finally:
        publication.await_and_ack()
    if publication.failures:
        raise publication.failures[0].error
    return result


_LIVE_PERSONS_BASE = """
    SELECT id, max(version) AS max_version, argMax(created_at, version) AS created_at
    FROM person
    WHERE team_id = %(team_id)s
    GROUP BY id
    HAVING argMax(is_deleted, version) = 0
"""

_LIVE_PERSONS_SCOPED = """
    SELECT id, max(version) AS max_version, argMax(created_at, version) AS created_at
    FROM person
    WHERE team_id = %(team_id)s AND id IN %(uuids)s
    GROUP BY id
    HAVING argMax(is_deleted, version) = 0
"""


def _ch_live_persons(team_id: int, uuids: Optional[list[str]]) -> dict[str, tuple[int, dt.datetime]]:
    """Map each non-deleted CH person id to its (max_version, created_at)."""
    # Two static query literals rather than an interpolated WHERE — every value is
    # bound through %(...)s params, so there's no user data in the SQL text itself.
    params: dict[str, object] = {"team_id": team_id}
    if uuids is None:
        query = _LIVE_PERSONS_BASE
    else:
        query = _LIVE_PERSONS_SCOPED
        params["uuids"] = list(uuids)

    rows = sync_execute(query, params)
    return {str(row[0]): (int(row[1]), row[2]) for row in rows}


def _ch_mappings_for_persons(team_id: int, orphan_uuids: set[str]) -> list[_Mapping]:
    """Return the current CH winner for every distinct_id ever tied to an orphan."""
    rows = sync_execute(
        """
            SELECT
                distinct_id,
                argMax(person_id, version) AS winner_person_id,
                argMax(is_deleted, version) AS winner_is_deleted,
                max(version) AS max_version
            FROM person_distinct_id2
            WHERE team_id = %(team_id)s AND distinct_id IN (
                SELECT DISTINCT distinct_id
                FROM person_distinct_id2
                WHERE team_id = %(team_id)s AND person_id IN %(orphans)s
            )
            GROUP BY distinct_id
        """,
        {"team_id": team_id, "orphans": list(orphan_uuids)},
    )
    return [
        _Mapping(
            distinct_id=row[0],
            winner_person_id=str(row[1]),
            winner_is_deleted=bool(row[2]),
            max_version=int(row[3]),
        )
        for row in rows
    ]


def _find_reverse_drift(team_id: int, deleted_winners: list[_Mapping], orphan_uuids: set[str]) -> list[tuple[str, str]]:
    """Among mappings whose winner is tombstoned, find those whose winning person
    is nonetheless live in the persons DB (CH-deleted / DB-live drift)."""
    winner_uuids = sorted({m.winner_person_id for m in deleted_winners if m.winner_person_id not in orphan_uuids})
    if not winner_uuids:
        return []

    live_in_db: set[str] = set()
    for start in range(0, len(winner_uuids), _PERSONHOG_UUID_BATCH):
        batch = winner_uuids[start : start + _PERSONHOG_UUID_BATCH]
        live_in_db.update(str(p.uuid) for p in get_persons_by_uuids(team_id, batch, distinct_id_limit=0))

    return sorted((m.distinct_id, m.winner_person_id) for m in deleted_winners if m.winner_person_id in live_in_db)
