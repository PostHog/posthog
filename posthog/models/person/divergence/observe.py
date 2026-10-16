"""Read one batch of keys from both stores into the classifier's state records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from posthog.models.person.divergence import lookups
from posthog.models.person.divergence.flavors import ChMapping, ChPerson, PgMapping, PgPerson
from posthog.models.person.util import get_distinct_id_rows, get_person_tombstones

PersonPgState = Literal["live", "deleted", "absent"]

# apply_deleted_mask = 0 shows lightweight-deleted rows, so a raise lands above every row a sweep masked.
_READ_SETTINGS = {"apply_deleted_mask": 0, "max_execution_time": 120, "max_memory_usage": 8_000_000_000}
_CH_CHUNK = 1_000
_OPERATION = "person_consistency_observe"

_CH_PERSONS_SELECT = """
SELECT
    toString(id),
    max(version),
    countIf(_row_exists),
    maxIfOrNull(version, _row_exists AND is_deleted = 0),
    maxIfOrNull(version, _row_exists AND is_deleted = 1),
    groupArrayIf(
        (version, cityHash64(properties, is_identified, is_deleted), properties = '{}' AND is_identified = 0),
        _row_exists
    ),
    maxIf(toUnixTimestamp(_timestamp), _row_exists)
FROM person
WHERE team_id = %(team_id)s AND {keys}
GROUP BY id
"""

_CH_MAPPINGS_SELECT = """
SELECT
    distinct_id,
    max(version),
    countIf(_row_exists),
    toString(argMaxIf(person_id, version, _row_exists)),
    maxIf(version, _row_exists),
    argMaxIf(is_deleted, version, _row_exists)
FROM person_distinct_id2
WHERE team_id = %(team_id)s AND {keys}
GROUP BY distinct_id
"""

# A range starts after `after`, or at it on a scan's first page, and ends at `last` inclusive.
_CH_PERSONS_SQL = _CH_PERSONS_SELECT.replace("{keys}", "id IN %(person_uuids)s")
_CH_PERSONS_RANGE_SQL = {
    first: _CH_PERSONS_SELECT.replace(
        "{keys}", f"id {'>=' if first else '>'} toUUID(%(after)s) AND id <= toUUID(%(last)s)"
    )
    for first in (True, False)
}
_CH_MAPPINGS_SQL = _CH_MAPPINGS_SELECT.replace("{keys}", "distinct_id IN %(distinct_ids)s")
_CH_MAPPINGS_RANGE_SQL = {
    first: _CH_MAPPINGS_SELECT.replace(
        "{keys}", f"distinct_id {'>=' if first else '>'} %(after)s AND distinct_id <= %(last)s"
    )
    for first in (True, False)
}


def ch_person_from_row(row: Sequence[Any]) -> tuple[str, ChPerson]:
    person_uuid, max_version, visible_rows, live_max, tomb_max, visible, newest_written_at = row
    visible_max = max((int(v) for v, _, _ in visible), default=None)
    at_max = [(payload, blank) for v, payload, blank in visible if visible_max is not None and int(v) == visible_max]
    earlier_had_properties = any(
        not blank for v, _, blank in visible if visible_max is not None and int(v) < visible_max
    )
    return str(person_uuid), ChPerson(
        max_version=int(max_version),
        visible_rows=int(visible_rows),
        live_max_version=None if live_max is None else int(live_max),
        tombstone_max_version=None if tomb_max is None else int(tomb_max),
        rows_at_max=len(at_max),
        payloads_at_max=len({payload for payload, _ in at_max}),
        winner_blanked=bool(at_max) and all(blank for _, blank in at_max) and earlier_had_properties,
        newest_written_at=float(newest_written_at) if int(visible_rows) else None,
    )


def ch_person_states(team_id: int, person_uuids: Sequence[str]) -> dict[str, ChPerson]:
    states: dict[str, ChPerson] = {}
    for chunk in lookups._chunks(list(person_uuids), _CH_CHUNK):
        rows = lookups._ch(_CH_PERSONS_SQL, {"team_id": team_id, "person_uuids": list(chunk)}, _READ_SETTINGS)
        states.update(ch_person_from_row(row) for row in rows)
    return states


def ch_person_states_in_range(team_id: int, after: str, last: str, *, first: bool) -> dict[str, ChPerson]:
    rows = lookups._ch(_CH_PERSONS_RANGE_SQL[first], {"team_id": team_id, "after": after, "last": last}, _READ_SETTINGS)
    return dict(ch_person_from_row(row) for row in rows)


def ch_mapping_from_row(row: Sequence[Any]) -> tuple[str, ChMapping]:
    distinct_id, max_version, visible_rows, owner, winner_version, winner_deleted = row
    return distinct_id, ChMapping(
        max_version=int(max_version),
        visible_rows=int(visible_rows),
        winner_person_uuid=str(owner),
        winner_version=int(winner_version),
        winner_deleted=bool(winner_deleted),
    )


def ch_mapping_states(team_id: int, distinct_ids: Sequence[str]) -> dict[str, ChMapping]:
    states: dict[str, ChMapping] = {}
    for chunk in lookups._chunks(list(distinct_ids), _CH_CHUNK):
        rows = lookups._ch(_CH_MAPPINGS_SQL, {"team_id": team_id, "distinct_ids": list(chunk)}, _READ_SETTINGS)
        states.update(ch_mapping_from_row(row) for row in rows)
    return states


def ch_mapping_states_in_range(team_id: int, after: str, last: str, *, first: bool) -> dict[str, ChMapping]:
    rows = lookups._ch(
        _CH_MAPPINGS_RANGE_SQL[first], {"team_id": team_id, "after": after, "last": last}, _READ_SETTINGS
    )
    return dict(ch_mapping_from_row(row) for row in rows)


def pg_person_states(team_id: int, person_uuids: Sequence[str]) -> dict[str, PgPerson]:
    """Live and tombstoned Postgres persons by uuid; absent uuids are left out."""
    uuids = list(person_uuids)
    live = {
        str(UUID(p.uuid)): PgPerson(id=int(p.id), version=int(p.version), is_deleted=False)
        for p in lookups._live_persons(team_id, uuids, _OPERATION)
    }
    missing = [UUID(u) for u in uuids if u not in live]
    tombstoned = {
        str(t.uuid): PgPerson(id=None, version=int(t.version), is_deleted=True)
        for t in (get_person_tombstones(team_id, missing) if missing else [])
    }
    return {**tombstoned, **live}


def pg_mapping_rows(team_id: int, distinct_ids: Sequence[str]) -> dict[str, PgMapping]:
    return {
        row.distinct_id: PgMapping(
            person_id=int(row.person_id),
            person_uuid=row.person_uuid if row.HasField("person_uuid") else None,
            version=int(row.version),
            is_deleted=row.is_deleted,
            person_is_deleted=row.person_is_deleted if row.HasField("person_is_deleted") else None,
        )
        for row in get_distinct_id_rows(team_id, list(distinct_ids))
    }


def person_pg_state(states: dict[str, PgPerson], person_uuid: str) -> PersonPgState:
    state = states.get(person_uuid)
    if state is None:
        return "absent"
    return "deleted" if state.is_deleted else "live"
