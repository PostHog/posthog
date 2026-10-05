import datetime as dt
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.models.person.util import (
    PersonTombstone,
    PersonTombstonePublication,
    create_person,
    create_person_distinct_id,
    get_person_tombstones,
    get_persons_by_uuids,
)

logger = structlog.get_logger(__name__)

# personhog clamps uuid lookups at 250 per request; batch to match.
_PERSONHOG_UUID_BATCH = 250


# ── Orphaned ClickHouse person repair ────────────────────────────────
#
# A person can be hard-deleted from the
# persons DB (posthog_person + posthog_persondistinctid) with no matching
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
    tombstoned_persons: int = 0
    # Orphans that are tombstoned in the persons DB, republished at the versions it holds.
    republished_persons: int = 0
    tombstoned_mappings: int = 0
    # distinct_id now won by a different, non-deleted CH mapping — left untouched
    # so the repair never resurrects-then-deletes a mapping that has been reassigned.
    skipped_reassigned_mappings: int = 0
    # (distinct_id, winner_uuid) pairs where the CH mapping is tombstoned but the
    # winning person is live in the persons DB — the opposite drift, handled by
    # person_divergence repair, reported here rather than repaired.
    reverse_drift_mappings: list[tuple[str, str]] = field(default_factory=list)
    dry_run: bool = False


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
    """Produce ClickHouse tombstones for orphaned persons and the distinct_id
    mappings they still win.

    A mapping is only tombstoned when its current CH winner is one of the orphans
    and is not already deleted. Mappings reassigned to another live person are
    skipped; mappings whose deleted winner is live in the persons DB are reported
    as reverse drift (not touched).

    Persons DB reads skip tombstoned rows, so a person that a deletion tombstoned in the
    persons DB without publishing to ClickHouse also looks like an orphan. Such a person is
    republished at the versions the persons DB holds instead of version + 100. A version
    + 100 tombstone would stay above the version that a later revival writes, so the
    revived person would stay hidden in ClickHouse. The lookup is read-only because the
    orphan read is eventually consistent: a live person can be reported as an orphan, and
    it must not be tombstoned in the persons DB for that.
    """
    result = OrphanRepairResult(orphaned_person_uuids=sorted(o.uuid for o in orphans), dry_run=dry_run)
    if not orphans:
        return result

    orphan_uuids = {o.uuid for o in orphans}
    to_tombstone: list[_Mapping] = []
    deleted_winners: list[_Mapping] = []
    for mapping in _ch_mappings_for_persons(team_id, orphan_uuids):
        if mapping.winner_is_deleted:
            deleted_winners.append(mapping)
        elif mapping.winner_person_id in orphan_uuids:
            to_tombstone.append(mapping)
        else:
            result.skipped_reassigned_mappings += 1

    result.reverse_drift_mappings = _find_reverse_drift(team_id, deleted_winners, orphan_uuids)

    # Raises rather than falling back to version + 100 for every orphan.
    stored = get_person_tombstones(team_id, [UUID(o.uuid) for o in orphans])
    stored_by_uuid = {str(t.uuid): t for t in stored}

    if dry_run:
        result.republished_persons = sum(1 for o in orphans if o.uuid in stored_by_uuid)
        result.tombstoned_persons = len(orphans) - result.republished_persons
        result.tombstoned_mappings = sum(1 for m in to_tombstone if m.winner_person_id not in stored_by_uuid)
        return result

    republished: set[str] = set()
    to_republish: list[tuple[PersonTombstone, Optional[dt.datetime]]] = []
    for orphan in orphans:
        tombstone = stored_by_uuid.get(orphan.uuid)
        if tombstone is not None:
            to_republish.append((tombstone, orphan.created_at))
            republished.add(orphan.uuid)
            continue
        # No persons-DB row exists, so derive the tombstone from ClickHouse. Version
        # + 100 makes the delete win over normal updates; stays below split's + 101.
        create_person(
            uuid=orphan.uuid,
            team_id=team_id,
            version=orphan.ch_max_version + 100,
            created_at=orphan.created_at,
            is_deleted=True,
        )
        result.tombstoned_persons += 1

    publication = PersonTombstonePublication(team_id=team_id, source="orphan_repair")
    publication.publish(to_republish)
    result.republished_persons = len(to_republish)

    for mapping in to_tombstone:
        if mapping.winner_person_id in republished:
            # The republish already produced this distinct ID at the stored version.
            continue
        create_person_distinct_id(
            team_id=team_id,
            distinct_id=mapping.distinct_id,
            person_id=mapping.winner_person_id,
            version=mapping.max_version + 100,
            is_deleted=True,
        )
        result.tombstoned_mappings += 1

    # Wait only after the mapping rows are produced. A rerun skips a person whose version + 100
    # row already landed, so a raise before this loop would leave its mappings live for good.
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
