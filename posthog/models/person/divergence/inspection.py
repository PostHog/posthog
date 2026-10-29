"""Classify explicit persons and mappings of one team, with the evidence each verdict rests on."""

from __future__ import annotations

import hashlib
import dataclasses
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.person.divergence import lookups, observe
from posthog.models.person.divergence.flavors import classify_mapping, classify_person
from posthog.models.person.util import list_person_tombstone_queue
from posthog.models.team import Team

KeyKind = Literal["person", "mapping"]


@frozen
class Inspection:
    kind: KeyKind
    team_id: int
    key: str
    flavor: str
    sub_flavor: str | None
    verb: str | None
    pg: dict[str, Any] | None
    ch: dict[str, Any] | None
    # For mappings: the owner ClickHouse names and that owner's Postgres state.
    ch_owner_pg_state: str | None = None
    # Every ClickHouse row of the key, lightweight-deleted ones included, oldest version first.
    ch_history: list[dict[str, Any]] | None = None
    activity: list[dict[str, Any]] | None = None
    tombstone_queue: dict[str, Any] | None = None


def hash_distinct_id(team_id: int, distinct_id: str) -> str:
    return hashlib.sha256(f"{team_id}:{distinct_id}".encode()).hexdigest()[:16]


def ghost_era(newest_written_at: float | None, purged_at: datetime | None) -> str:
    if purged_at is not None and newest_written_at is not None and newest_written_at < purged_at.timestamp():
        return "after_purge"
    return "historical"


def _asdict(state: Any) -> dict[str, Any] | None:
    return None if state is None else dataclasses.asdict(state)


_HISTORY_LIMIT = 50
_ACTIVITY_LIMIT = 20

_PERSON_HISTORY_SQL = """
SELECT toString(id), version, is_deleted, is_identified, length(properties), toString(_timestamp), _row_exists
FROM person
WHERE team_id = %(team_id)s AND id IN %(keys)s
ORDER BY id, version, _timestamp
LIMIT %(limit)s BY id
"""

_MAPPING_HISTORY_SQL = """
SELECT distinct_id, toString(person_id), version, is_deleted, toString(_timestamp), _row_exists
FROM person_distinct_id2
WHERE team_id = %(team_id)s AND distinct_id IN %(keys)s
ORDER BY distinct_id, version, _timestamp
LIMIT %(limit)s BY distinct_id
"""


def _person_history(team_id: int, person_uuids: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    history: dict[str, list[dict[str, Any]]] = {u: [] for u in person_uuids}
    if not person_uuids:
        return history
    rows = lookups._ch(
        _PERSON_HISTORY_SQL,
        {"team_id": team_id, "keys": list(person_uuids), "limit": _HISTORY_LIMIT},
        observe._READ_SETTINGS,
    )
    for person_uuid, version, is_deleted, is_identified, properties_bytes, written_at, row_exists in rows:
        history.setdefault(person_uuid, []).append(
            {
                "version": int(version),
                "is_deleted": bool(is_deleted),
                "is_identified": bool(is_identified),
                "properties_bytes": int(properties_bytes),
                "written_at": written_at,
                "visible": bool(row_exists),
            }
        )
    return history


def _mapping_history(team_id: int, distinct_ids: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    history: dict[str, list[dict[str, Any]]] = {d: [] for d in distinct_ids}
    if not distinct_ids:
        return history
    rows = lookups._ch(
        _MAPPING_HISTORY_SQL,
        {"team_id": team_id, "keys": list(distinct_ids), "limit": _HISTORY_LIMIT},
        observe._READ_SETTINGS,
    )
    for distinct_id, person_uuid, version, is_deleted, written_at, row_exists in rows:
        history.setdefault(distinct_id, []).append(
            {
                "person_uuid": person_uuid,
                "version": int(version),
                "is_deleted": bool(is_deleted),
                "written_at": written_at,
                "visible": bool(row_exists),
            }
        )
    return history


def _activity(team_id: int, person_uuid: str, person_id: int | None) -> list[dict[str, Any]]:
    # Deletes and splits name the person by uuid in detail.name, which the GIN index on detail serves.
    # Property edits carry only item_id, and a tombstoned or purged person has no known pk.
    names_person = Q(detail__contains={"name": person_uuid})
    if person_id is not None:
        names_person |= Q(item_id=str(person_id))
    entries = (
        ActivityLog.objects.filter(names_person, team_id=team_id, scope="Person")
        .order_by("-created_at")
        .values("activity", "created_at", "user_id", "was_impersonated", "is_system")[:_ACTIVITY_LIMIT]
    )
    return [{**entry, "created_at": entry["created_at"].isoformat()} for entry in entries]


def _tombstone_queue_entry(team_id: int, person_uuid: str) -> dict[str, Any] | None:
    # The queue is keyset-paged after (team, uuid), so start just below this uuid to read exactly its entry.
    before = UUID(int=UUID(person_uuid).int - 1) if UUID(person_uuid).int else None
    entries = list_person_tombstone_queue((team_id, before) if before else None, 1, team_id=team_id)
    entry = next((e for e in entries if str(e.person_uuid) == person_uuid), None)
    if entry is None:
        return None
    return {"person_version": entry.person_version, "tombstoned_at_ms": entry.tombstoned_at_ms}


def inspect_persons(
    team_id: int, person_uuids: Sequence[str], *, purged_at: datetime | None = None
) -> list[Inspection]:
    # Every store keys persons by the canonical lowercase form, so other spellings would read as absent.
    uuids = list(dict.fromkeys(str(UUID(u)) for u in person_uuids))
    team_exists = Team.objects.filter(id=team_id).exists()
    pg = observe.pg_person_states(team_id, uuids) if team_exists else {}
    ch = observe.ch_person_states(team_id, uuids)
    history = _person_history(team_id, uuids)
    results = []
    for person_uuid in uuids:
        pg_state = pg.get(person_uuid)
        ch_state = ch.get(person_uuid)
        verdict = classify_person(
            pg_state,
            ch_state,
            team_exists=team_exists,
            ghost_era=ghost_era(ch_state.newest_written_at if ch_state else None, purged_at),
        )
        results.append(
            Inspection(
                kind="person",
                team_id=team_id,
                key=person_uuid,
                flavor=verdict.flavor,
                sub_flavor=verdict.sub_flavor,
                verb=verdict.verb,
                pg=_asdict(pg_state),
                ch=_asdict(ch_state),
                ch_history=history[person_uuid],
                activity=_activity(team_id, person_uuid, pg_state.id if pg_state else None),
                tombstone_queue=_tombstone_queue_entry(team_id, person_uuid) if team_exists else None,
            )
        )
    return results


def inspect_mappings(team_id: int, distinct_ids: Sequence[str]) -> list[Inspection]:
    dids = list(dict.fromkeys(distinct_ids))
    team_exists = Team.objects.filter(id=team_id).exists()
    pg = observe.pg_mapping_rows(team_id, dids) if team_exists else {}
    ch = observe.ch_mapping_states(team_id, dids)
    owners = sorted({c.winner_person_uuid for c in ch.values()})
    owner_states = observe.pg_person_states(team_id, owners) if team_exists and owners else {}
    history = _mapping_history(team_id, dids)
    results = []
    for distinct_id in dids:
        ch_state = ch.get(distinct_id)
        owner_state = observe.person_pg_state(owner_states, ch_state.winner_person_uuid) if ch_state else None
        verdict = classify_mapping(
            pg.get(distinct_id), ch_state, ch_owner_pg_state=owner_state, team_exists=team_exists
        )
        results.append(
            Inspection(
                kind="mapping",
                team_id=team_id,
                key=distinct_id,
                flavor=verdict.flavor,
                sub_flavor=verdict.sub_flavor,
                verb=verdict.verb,
                pg=_asdict(pg.get(distinct_id)),
                ch=_asdict(ch_state),
                ch_owner_pg_state=owner_state,
                ch_history=history[distinct_id],
            )
        )
    return results
