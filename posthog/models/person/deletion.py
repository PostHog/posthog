import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import structlog
from rest_framework.exceptions import NotFound

from posthog.clickhouse.client import sync_execute
from posthog.models.person import Person
from posthog.models.person.util import create_person, create_person_distinct_id, get_persons_by_uuids

logger = structlog.get_logger(__name__)

# personhog clamps uuid lookups at 250 per request; batch to match.
_PERSONHOG_UUID_BATCH = 250


def reset_all_deleted_person_distinct_ids(team_id: int, version: int = 2500):
    # NOTE: Version is arbitrary, we just need to make sure it's higher than any existing version
    distinct_ids = _get_distinct_ids_tied_to_deleted_persons(team_id)
    distinct_ids_and_versions: list[tuple[str, int]] = [(distinct_id, version) for distinct_id in distinct_ids]
    _updated_distinct_ids(team_id, distinct_ids_and_versions)


def reset_deleted_person_distinct_ids(team_id: int, distinct_id: str):
    existing_version = _get_version_for_distinct_id(team_id, distinct_id)
    distinct_ids_and_versions = [(distinct_id, existing_version + 100)]

    logger.info(f"Resetting distinct id {distinct_id} to version {existing_version + 100}")
    _updated_distinct_ids(team_id, distinct_ids_and_versions)


def _get_distinct_ids_tied_to_deleted_persons(team_id: int) -> list[str]:
    # find distinct_ids where the person is set to be deleted
    rows = sync_execute(
        """
            SELECT distinct_id FROM (
                SELECT distinct_id, argMax(person_id, version) AS person_id FROM person_distinct_id2 WHERE team_id = %(team)s GROUP BY distinct_id
            ) AS pdi2
            WHERE pdi2.person_id NOT IN (SELECT id FROM person WHERE team_id = %(team)s)
            OR
            pdi2.person_id IN (SELECT id FROM person WHERE team_id = %(team)s AND is_deleted = 1)
        """,
        {
            "team": team_id,
        },
    )
    return [row[0] for row in rows]


def _get_version_for_distinct_id(team_id: int, distinct_id: str) -> int:
    rows = sync_execute(
        """
            SELECT max(version) as version FROM person_distinct_id2 WHERE team_id = %(team)s AND distinct_id = %(distinct_id)s
        """,
        {
            "team": team_id,
            "distinct_id": distinct_id,
        },
    )

    if len(rows) == 0:
        raise NotFound(f"Distinct id {distinct_id} not found")
    return rows[0][0]


def _updated_distinct_ids(team_id: int, distinct_id_versions: list[tuple[str, int]]):
    reset_person_uuids: set[str] = set()

    for distinct_id, version in distinct_id_versions:
        # this can throw but this script can safely be re-run as
        # updated distinct_ids won't show up in the search anymore
        # since they no longer belong to deleted persons
        # it's safer to throw and exit if anything went wrong

        # The write goes through personhog (an external RPC that can't join a
        # Postgres transaction), so there is no surrounding atomic block.
        person = _update_distinct_id_in_postgres(distinct_id, version, team_id)

        # Update ClickHouse via Kafka message
        if person:
            person_uuid = str(person.uuid)

            create_person_distinct_id(
                team_id=team_id,
                distinct_id=distinct_id,
                person_id=person_uuid,
                version=version,
                is_deleted=False,
            )

            # Also reset the person record in ClickHouse — the soft-deleted person row
            # has a high version that causes ReplacingMergeTree to keep the deleted state,
            # making the person invisible to analytics queries
            if person_uuid not in reset_person_uuids:
                reset_person_uuids.add(person_uuid)
                _reset_person_in_clickhouse(team_id, person)


def _update_distinct_id_in_postgres(distinct_id: str, version: int, team_id: int) -> Optional[Person]:
    """Raise the distinct_id's version to at least `version` and return its person.

    Routes through SetPersonDistinctIdVersionFloor (guarded — never lowers the
    version). Returns None when the distinct_id doesn't exist (it hasn't been
    re-used yet).
    """
    from posthog.personhog_client.client import personhog_call

    return personhog_call(
        "set_person_distinct_id_version_floor",
        lambda: _set_distinct_id_version_floor_via_personhog(team_id, distinct_id, version),
    )


def _set_distinct_id_version_floor_via_personhog(team_id: int, distinct_id: str, version: int) -> Optional[Person]:
    from posthog.personhog_client.client import require_personhog_client
    from posthog.personhog_client.converters import proto_person_to_model
    from posthog.personhog_client.proto import SetPersonDistinctIdVersionFloorRequest

    client = require_personhog_client()

    resp = client.set_person_distinct_id_version_floor(
        SetPersonDistinctIdVersionFloorRequest(team_id=team_id, distinct_id=distinct_id, min_version=version)
    )
    if not resp.HasField("person"):
        logger.info(f"Distinct id {distinct_id} hasn't been re-used yet and can cause problems in the future")
        return None
    return proto_person_to_model(resp.person, distinct_ids=[distinct_id])


def _get_person_version_if_deleted(team_id: int, person_uuid: str) -> Optional[int]:
    """Returns the max version if the person is soft-deleted in ClickHouse, None otherwise."""
    rows = sync_execute(
        """
            SELECT max(version), argMax(is_deleted, version)
            FROM person
            WHERE team_id = %(team_id)s AND id = %(person_id)s
        """,
        {"team_id": team_id, "person_id": person_uuid},
    )
    if len(rows) == 0:
        return None
    max_version, is_deleted = rows[0]
    if not is_deleted:
        return None
    return max_version


def _reset_person_in_clickhouse(team_id: int, person: Person) -> None:
    person_uuid = str(person.uuid)
    max_version = _get_person_version_if_deleted(team_id, person_uuid)
    if max_version is None:
        return

    new_version = max_version + 100
    logger.info(f"Resetting person {person_uuid} in ClickHouse to version {new_version}")

    # Raise the Postgres version so future updates from the plugin-server (which
    # reads version from Postgres) won't be ignored by ClickHouse.
    _set_person_version_floor(team_id, person.pk, new_version)

    create_person(
        uuid=person_uuid,
        team_id=team_id,
        version=new_version,
        properties=person.properties,
        is_identified=person.is_identified,
        is_deleted=False,
        created_at=person.created_at,
    )


def _set_person_version_floor(team_id: int, person_id: int, new_version: int) -> None:
    """Raise a person's version to at least `new_version` (guarded — never lowers).

    Routes through SetPersonVersionFloor.
    """
    from posthog.personhog_client.client import personhog_call

    personhog_call(
        "set_person_version_floor",
        lambda: _set_person_version_floor_via_personhog(team_id, person_id, new_version),
    )


def _set_person_version_floor_via_personhog(team_id: int, person_id: int, new_version: int) -> None:
    from posthog.personhog_client.client import require_personhog_client
    from posthog.personhog_client.proto import SetPersonVersionFloorRequest

    client = require_personhog_client()

    client.set_person_version_floor(
        SetPersonVersionFloorRequest(team_id=team_id, person_id=person_id, min_version=new_version)
    )


# ── Orphaned ClickHouse person repair ────────────────────────────────
#
# The inverse of the reset helpers above: a person can be hard-deleted from the
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


@dataclass
class OrphanRepairResult:
    orphaned_person_uuids: list[str]
    tombstoned_persons: int = 0
    tombstoned_mappings: int = 0
    # distinct_id now won by a different, non-deleted CH mapping — left untouched
    # so the repair never resurrects-then-deletes a mapping that has been reassigned.
    skipped_reassigned_mappings: int = 0
    # (distinct_id, winner_uuid) pairs where the CH mapping is tombstoned but the
    # winning person is live in the persons DB — the opposite drift, handled by
    # reset_all_deleted_person_distinct_ids, reported here rather than repaired.
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

    if dry_run:
        result.tombstoned_persons = len(orphans)
        result.tombstoned_mappings = len(to_tombstone)
        return result

    for orphan in orphans:
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

    for mapping in to_tombstone:
        create_person_distinct_id(
            team_id=team_id,
            distinct_id=mapping.distinct_id,
            person_id=mapping.winner_person_id,
            version=mapping.max_version + 100,
            is_deleted=True,
        )
        result.tombstoned_mappings += 1

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
