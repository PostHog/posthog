"""Reads ClickHouse state for target persons and plans what the repair writes."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from posthog.dataclasses import frozen
from posthog.models.person import Person
from posthog.models.person.util import _batched_get_distinct_ids_for_persons, get_persons_by_uuids
from posthog.personhog_client.client import personhog_call

from . import datatypes, lookups

# Repair reads see lightweight-deleted rows, so a republish lands above every row a sweep masked.
_REPAIR_READ_SETTINGS = {"apply_deleted_mask": 0, "max_execution_time": 60, "max_memory_usage": 4_000_000_000}

_MAPPING_QUERY_CHUNK_SIZE = 1_000

# A person with more distinct ids keeps its person repair, and its mappings are reported for a separate plan:
# one read of every mapping can exceed the gRPC message limit, and their paced writes would run for hours.
_MAX_REPAIR_DISTINCT_IDS_PER_PERSON = 1_000


@frozen
class _ChPersonState:
    visible_rows: int
    visible_max_version: int
    visible_winner_deleted: bool
    # Includes lightweight-deleted rows, so a republish lands above every row the sweep masked.
    max_version: int


@frozen
class _ChMappingState:
    visible_rows: int
    visible_max_version: int
    visible_winner_deleted: bool
    visible_winner_person_uuid: str
    max_version: int


@frozen
class _MappingPlan:
    distinct_id: str
    kind: datatypes.MappingDivergenceKind | None
    pg_version: int
    ch_max_version: int | None
    target_version: int


@frozen
class _PersonPlan:
    team_id: int
    person_uuid: str
    person: Person | None
    kind: datatypes.PersonDivergenceKind | None
    ch_max_version: int | None
    target_version: int | None
    mappings: list[_MappingPlan]
    too_many_distinct_ids: bool = False


_PERSON_STATE_SQL = """
SELECT
    toString(id),
    countIf(_row_exists),
    maxIf(version, _row_exists),
    argMaxIf(is_deleted, version, _row_exists),
    max(version)
FROM person
WHERE team_id = %(team_id)s AND id IN %(person_uuids)s
GROUP BY id
"""

_MAPPING_STATE_SQL = """
SELECT
    distinct_id,
    countIf(_row_exists),
    maxIf(version, _row_exists),
    argMaxIf(is_deleted, version, _row_exists),
    toString(argMaxIf(person_id, version, _row_exists)),
    max(version)
FROM person_distinct_id2
WHERE team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s
GROUP BY distinct_id
"""


def _person_kind(pg_version: int, state: _ChPersonState | None) -> datatypes.PersonDivergenceKind | None:
    # Any winner that differs from Postgres counts, whatever the versions: a raise whose publish
    # never landed leaves ClickHouse below Postgres, and a rerun must still finish it.
    if state is None:
        return "absent"
    if state.visible_rows == 0:
        return "swept"
    if state.visible_winner_deleted:
        return "hidden"
    if state.visible_max_version > pg_version:
        return "stale"
    if state.visible_max_version < pg_version:
        return "behind"
    return None


def _mapping_kind(
    person_uuid: str, pg_version: int, state: _ChMappingState | None
) -> datatypes.MappingDivergenceKind | None:
    if state is None or state.visible_rows == 0:
        return "absent"
    if state.visible_winner_deleted:
        return "hidden"
    if state.visible_winner_person_uuid != person_uuid:
        return "other_person"
    # The owner matches, but a later move of this mapping would be written below the ClickHouse winner and lost.
    if state.visible_max_version > pg_version:
        return "stale"
    return None


def _target_version(pg_version: int, ch_max_version: int | None) -> int:
    # One above ClickHouse, not 100 above: a later Postgres write or tombstone takes the next version
    # and must outrank this row.
    return pg_version if ch_max_version is None else max(pg_version, ch_max_version + 1)


def _ch_person_states(team_id: int, person_uuids: list[str]) -> dict[str, _ChPersonState]:
    rows = lookups._ch(_PERSON_STATE_SQL, {"team_id": team_id, "person_uuids": person_uuids}, _REPAIR_READ_SETTINGS)
    return {
        person_uuid: _ChPersonState(
            visible_rows=int(visible_rows),
            visible_max_version=int(visible_max_version),
            visible_winner_deleted=bool(visible_winner_deleted),
            max_version=int(max_version),
        )
        for person_uuid, visible_rows, visible_max_version, visible_winner_deleted, max_version in rows
    }


def _ch_mapping_states(team_id: int, distinct_ids: list[str]) -> dict[str, _ChMappingState]:
    states: dict[str, _ChMappingState] = {}
    for chunk in lookups._chunks(distinct_ids, _MAPPING_QUERY_CHUNK_SIZE):
        rows = lookups._ch(_MAPPING_STATE_SQL, {"team_id": team_id, "distinct_ids": list(chunk)}, _REPAIR_READ_SETTINGS)
        for (
            distinct_id,
            visible_rows,
            visible_max_version,
            visible_winner_deleted,
            visible_winner_person_uuid,
            max_version,
        ) in rows:
            states[distinct_id] = _ChMappingState(
                visible_rows=int(visible_rows),
                visible_max_version=int(visible_max_version),
                visible_winner_deleted=bool(visible_winner_deleted),
                visible_winner_person_uuid=visible_winner_person_uuid,
                max_version=int(max_version),
            )
    return states


def _plan_chunk(
    team_id: int,
    person_uuids: Sequence[str],
    *,
    only_distinct_id: str | None = None,
    republish_equal: Collection[str] = (),
) -> list[_PersonPlan]:
    """`republish_equal` names persons to republish even when ClickHouse holds their Postgres version, because
    a scan found other content at that version."""
    live = {str(p.uuid): p for p in get_persons_by_uuids(team_id, list(person_uuids), distinct_id_limit=0)}
    person_states = _ch_person_states(team_id, list(live)) if live else {}
    distinct_ids_by_person = (
        personhog_call(
            "person_divergence_repair_distinct_ids",
            lambda: _batched_get_distinct_ids_for_persons(
                team_id, [p.pk for p in live.values()], limit_per_person=_MAX_REPAIR_DISTINCT_IDS_PER_PERSON + 1
            ),
        )
        if live
        else {}
    )
    too_many: set[int] = set()
    all_distinct_ids: list[str] = []
    for person_id, dids in list(distinct_ids_by_person.items()):
        over_cap = len(dids) > _MAX_REPAIR_DISTINCT_IDS_PER_PERSON
        if only_distinct_id is not None:
            dids = [d for d in dids if d.id == only_distinct_id]
            distinct_ids_by_person[person_id] = dids
            # The capped read can miss the requested id, which must then be reported rather than dropped.
            over_cap = over_cap and not dids
        if over_cap:
            too_many.add(person_id)
        else:
            all_distinct_ids.extend(d.id for d in dids)
    mapping_states = _ch_mapping_states(team_id, all_distinct_ids) if all_distinct_ids else {}

    plans: list[_PersonPlan] = []
    for person_uuid in person_uuids:
        person = live.get(person_uuid)
        if person is None:
            plans.append(
                _PersonPlan(
                    team_id=team_id,
                    person_uuid=person_uuid,
                    person=None,
                    kind=None,
                    ch_max_version=None,
                    target_version=None,
                    mappings=[],
                )
            )
            continue
        pg_version = int(person.version or 0)
        state = person_states.get(person_uuid)
        ch_max_version = state.max_version if state is not None else None
        person_distinct_ids = distinct_ids_by_person.get(person.pk, [])
        too_many_distinct_ids = person.pk in too_many
        mappings = []
        for mapping in [] if too_many_distinct_ids else person_distinct_ids:
            mapping_state = mapping_states.get(mapping.id)
            mapping_ch_max = mapping_state.max_version if mapping_state is not None else None
            mappings.append(
                _MappingPlan(
                    distinct_id=mapping.id,
                    kind=_mapping_kind(person_uuid, mapping.version, mapping_state),
                    pg_version=mapping.version,
                    ch_max_version=mapping_ch_max,
                    target_version=_target_version(mapping.version, mapping_ch_max),
                )
            )
        plans.append(
            _PersonPlan(
                team_id=team_id,
                person_uuid=person_uuid,
                person=person,
                kind=_person_kind(pg_version, state)
                or ("equal" if person_uuid in republish_equal and state is not None and state.visible_rows else None),
                ch_max_version=ch_max_version,
                target_version=_target_version(pg_version, ch_max_version),
                mappings=mappings,
                too_many_distinct_ids=too_many_distinct_ids,
            )
        )
    return plans
