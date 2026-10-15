"""Classify explicit persons and mappings of one team, with the evidence each verdict rests on."""

from __future__ import annotations

import hashlib
import dataclasses
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from posthog.dataclasses import frozen
from posthog.models.person.divergence import observe
from posthog.models.person.divergence.flavors import classify_mapping, classify_person
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


def hash_distinct_id(team_id: int, distinct_id: str) -> str:
    return hashlib.sha256(f"{team_id}:{distinct_id}".encode()).hexdigest()[:16]


def ghost_era(newest_written_at: float | None, purged_at: datetime | None) -> str:
    if purged_at is not None and newest_written_at is not None and newest_written_at < purged_at.timestamp():
        return "after_purge"
    return "historical"


def _asdict(state: Any) -> dict[str, Any] | None:
    return None if state is None else dataclasses.asdict(state)


def inspect_persons(
    team_id: int, person_uuids: Sequence[str], *, purged_at: datetime | None = None
) -> list[Inspection]:
    uuids = list(dict.fromkeys(person_uuids))
    team_exists = Team.objects.filter(id=team_id).exists()
    pg = observe.pg_person_states(team_id, uuids) if team_exists else {}
    ch = observe.ch_person_states(team_id, uuids)
    results = []
    for person_uuid in uuids:
        ch_state = ch.get(person_uuid)
        verdict = classify_person(
            pg.get(person_uuid),
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
                pg=_asdict(pg.get(person_uuid)),
                ch=_asdict(ch_state),
            )
        )
    return results


def inspect_mappings(team_id: int, distinct_ids: Sequence[str]) -> list[Inspection]:
    dids = list(dict.fromkeys(distinct_ids))
    pg = observe.pg_mapping_rows(team_id, dids)
    ch = observe.ch_mapping_states(team_id, dids)
    owners = sorted({c.winner_person_uuid for c in ch.values()})
    owner_states = observe.pg_person_states(team_id, owners) if owners else {}
    results = []
    for distinct_id in dids:
        ch_state = ch.get(distinct_id)
        owner_state = observe.person_pg_state(owner_states, ch_state.winner_person_uuid) if ch_state else None
        verdict = classify_mapping(pg.get(distinct_id), ch_state, ch_owner_pg_state=owner_state)
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
            )
        )
    return results
