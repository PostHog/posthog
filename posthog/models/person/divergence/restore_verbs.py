"""Repair verbs that rebuild Postgres from ClickHouse: restore a lost person with its distinct ids, fold a lost
person into the person that holds its distinct ids now, or merge two live persons through ingestion."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from posthog.api.capture import capture_internal
from posthog.dataclasses import frozen
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_PERSON
from posthog.models.person.deletion import find_orphaned_ch_persons, tombstone_orphaned_ch_persons
from posthog.models.person.sql import INSERT_PERSON_SQL
from posthog.models.person.util import (
    _person_row,
    create_person_distinct_id,
    get_distinct_id_rows,
    get_persons_by_uuids,
)
from posthog.models.team import Team
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.proto import (
    DISTINCT_ID_WRITE_ACTION_INSERT,
    DISTINCT_ID_WRITE_ACTION_RAISE,
    DISTINCT_ID_WRITE_OUTCOME_APPLIED,
    DISTINCT_ID_WRITE_OUTCOME_PERSON_NOT_LIVE,
    DISTINCT_ID_WRITE_OUTCOME_UNCHANGED,
    RESTORE_OUTCOME_EXISTS_LIVE,
    RESTORE_OUTCOME_INSERTED,
    DistinctIdWrite,
    RestoredPerson,
    RestorePersonsRequest,
    WriteDistinctIdsRequest,
)

from . import lookups, observe, repairs, stale_merge

if TYPE_CHECKING:
    from .verbs import VerbContext

# The most rows a personhog repair write takes in one call.
_BATCH = 250

_LIVE = "is_deleted = 0 AND _row_exists"
_PAYLOAD_SQL = f"""
SELECT
    toString(id),
    max(version),
    countIf({_LIVE}),
    maxIf(version, {_LIVE}),
    maxIfOrNull(version, is_deleted = 1 AND _row_exists),
    argMaxIf(properties, version, {_LIVE}),
    argMaxIf(is_identified, version, {_LIVE}),
    argMaxIf(created_at, version, {_LIVE})
FROM person
WHERE team_id = %(team_id)s AND id IN %(person_uuids)s
GROUP BY id
"""


@frozen
class _Payload:
    max_version: int
    properties: dict[str, Any]
    is_identified: bool
    created_at: datetime


def _live_payloads(team_id: int, person_uuids: Sequence[str]) -> dict[str, _Payload]:
    """The ClickHouse winner of each person that ClickHouse still shows live, with what a restore copies."""
    payloads: dict[str, _Payload] = {}
    for chunk in lookups._chunks(list(person_uuids), 1_000):
        rows = lookups._ch(_PAYLOAD_SQL, {"team_id": team_id, "person_uuids": list(chunk)}, observe._READ_SETTINGS)
        for person_uuid, max_version, live_rows, live_max, tomb_max, properties, is_identified, created_at in rows:
            # A tie counts as visible, as in the classifier: ClickHouse may return either row.
            if not live_rows or (tomb_max is not None and int(tomb_max) > int(live_max)):
                continue
            payloads[str(person_uuid)] = _Payload(
                max_version=int(max_version),
                properties=json.loads(properties) if properties else {},
                is_identified=bool(is_identified),
                created_at=created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC),
            )
    return payloads


def _publish_person(team_id: int, person_uuid: str, payload: _Payload, version: int) -> Any:
    row = _person_row(
        team_id=team_id,
        uuid=person_uuid,
        version=version,
        properties=payload.properties,
        is_identified=payload.is_identified,
        is_deleted=False,
        created_at=payload.created_at,
        last_seen_at=None,
    )
    row["last_seen_at"] = None
    return ClickhouseProducer().produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=row)


def _mapping_write(row: dict[str, Any], target: str, ch_max: int | None) -> DistinctIdWrite:
    """Insert where Postgres has no row; otherwise raise the row Postgres already points at the target, while it
    holds the reported version."""
    pg = row["evidence"]["pg"]
    min_version = max(int(pg["version"]) if pg else 0, (ch_max + 1) if ch_max is not None else 0)
    if pg is None:
        return DistinctIdWrite(
            distinct_id=row["key"], action=DISTINCT_ID_WRITE_ACTION_INSERT, person_uuid=target, min_version=min_version
        )
    return DistinctIdWrite(
        distinct_id=row["key"],
        action=DISTINCT_ID_WRITE_ACTION_RAISE,
        person_uuid=target,
        min_version=min_version,
        expected_version=int(pg["version"]),
    )


def _write_mappings(context: VerbContext, rows: list[dict[str, Any]], targets: dict[str, str], done: str) -> list[str]:
    """Point each row's mapping at its target person: insert where Postgres has no row, raise where Postgres
    already names the target. Publishes what Postgres stores and returns the distinct ids that now point there."""
    moved: list[str] = []
    for batch in lookups._chunks(rows, _BATCH):
        ch = observe.ch_mapping_states(context.team_id, [r["key"] for r in batch])
        writes = []
        for row in batch:
            state = ch.get(row["key"])
            writes.append(_mapping_write(row, targets[row["key"]], state.max_version if state else None))
        by_key = {row["key"]: row for row in batch}
        if not context.apply:
            current = {r.distinct_id: r for r in get_distinct_id_rows(context.team_id, list(by_key), strong=True)}
            for write in writes:
                now = current.get(write.distinct_id)
                expected = (
                    now is None
                    if write.action == DISTINCT_ID_WRITE_ACTION_INSERT
                    else now is not None
                    and not now.is_deleted
                    and now.person_uuid == write.person_uuid
                    and now.version == write.expected_version
                )
                context.action(
                    by_key[write.distinct_id],
                    "would_repair" if expected else "skipped_changed",
                    target_person=write.person_uuid,
                    target_version=write.min_version,
                )
            continue
        context.pacer.before_write()
        response = personhog_call(
            "person_consistency_write_distinct_ids",
            partial(
                require_personhog_client().write_distinct_ids,
                WriteDistinctIdsRequest(team_id=context.team_id, writes=writes),
            ),
        )
        wanted = {w.distinct_id: w for w in writes}
        for result in response.results:
            write = wanted[result.distinct_id]
            stored = result.row if result.HasField("row") else None
            in_place = (
                stored is not None
                and not stored.is_deleted
                and stored.person_uuid == write.person_uuid
                and stored.version >= write.min_version
            )
            if stored is not None and (
                result.outcome in (DISTINCT_ID_WRITE_OUTCOME_APPLIED, DISTINCT_ID_WRITE_OUTCOME_UNCHANGED) or in_place
            ):
                context.deliveries.track(
                    create_person_distinct_id(
                        context.team_id, result.distinct_id, write.person_uuid, version=int(stored.version)
                    )
                )
                outcome = done if result.outcome == DISTINCT_ID_WRITE_OUTCOME_APPLIED else f"already_{done}"
                context.action(
                    by_key[result.distinct_id], outcome, target_person=write.person_uuid, version=int(stored.version)
                )
                moved.append(result.distinct_id)
            elif result.outcome == DISTINCT_ID_WRITE_OUTCOME_PERSON_NOT_LIVE:
                context.action(by_key[result.distinct_id], "skipped_person_not_live", target_person=write.person_uuid)
            else:
                context.action(by_key[result.distinct_id], "skipped_changed", target_person=write.person_uuid)
    return moved


def restore(rows: list[dict[str, Any]], context: VerbContext) -> None:
    """Insert lost persons into Postgres from their ClickHouse winner, one version above ClickHouse, then their
    lost distinct ids, and publish both. A person or mapping that exists again in Postgres is left alone."""
    mapping_rows = [r for r in rows if r["kind"] == "mapping"]
    with_ids = {r["evidence"]["ch"]["winner_person_uuid"] for r in mapping_rows}
    person_rows = []
    for row in (r for r in rows if r["kind"] == "person"):
        if row["key"] in with_ids:
            person_rows.append(row)
        else:
            # Restored alone, the person would have no distinct id, so nothing could reach it.
            context.action(row, "skipped_no_distinct_id")
    restored = _restore_persons(person_rows, context)
    if not mapping_rows:
        return
    targets = {r["key"]: r["evidence"]["ch"]["winner_person_uuid"] for r in mapping_rows}
    if context.apply:
        # A mapping of a person this run did not restore would only fail on the person; report it instead.
        reported_persons = {r["key"] for r in person_rows}
        blocked = [
            r for r in mapping_rows if targets[r["key"]] in reported_persons and targets[r["key"]] not in restored
        ]
        for row in blocked:
            context.action(row, "skipped_person_not_restored", target_person=targets[row["key"]])
        mapping_rows = [r for r in mapping_rows if r not in blocked]
    _write_mappings(context, mapping_rows, targets, "restored")


def _restore_persons(rows: list[dict[str, Any]], context: VerbContext) -> set[str]:
    restored: set[str] = set()
    for batch in lookups._chunks(rows, _BATCH):
        by_uuid = {row["key"]: row for row in batch}
        payloads = _live_payloads(context.team_id, list(by_uuid))
        in_postgres = observe.pg_person_states(context.team_id, list(by_uuid))
        candidates: list[str] = []
        for person_uuid, row in by_uuid.items():
            if person_uuid in in_postgres:
                context.action(
                    row,
                    "skipped_exists_live" if not in_postgres[person_uuid].is_deleted else "skipped_exists_tombstoned",
                )
            elif person_uuid not in payloads:
                context.action(row, "skipped_not_divergent")
            else:
                candidates.append(person_uuid)
        if not candidates:
            continue
        if not context.apply:
            for person_uuid in candidates:
                context.action(
                    by_uuid[person_uuid], "would_repair", target_version=payloads[person_uuid].max_version + 1
                )
            continue
        context.pacer.before_write()
        request = RestorePersonsRequest(
            team_id=context.team_id,
            persons=[
                RestoredPerson(
                    person_uuid=u,
                    properties=json.dumps(payloads[u].properties).encode(),
                    created_at_ms=int(payloads[u].created_at.timestamp() * 1000),
                    is_identified=payloads[u].is_identified,
                    version=payloads[u].max_version + 1,
                )
                for u in candidates
            ],
        )
        response = personhog_call(
            "person_consistency_restore_persons", partial(require_personhog_client().restore_persons, request)
        )
        for result in response.results:
            row = by_uuid[result.person_uuid]
            if result.outcome == RESTORE_OUTCOME_INSERTED:
                context.deliveries.track(
                    _publish_person(
                        context.team_id, result.person_uuid, payloads[result.person_uuid], int(result.version)
                    )
                )
                restored.add(result.person_uuid)
                context.action(row, "restored", version=int(result.version))
            else:
                live = result.outcome == RESTORE_OUTCOME_EXISTS_LIVE
                context.action(row, "skipped_exists_live" if live else "skipped_exists_tombstoned")
    return restored


@frozen
class _Pair:
    # The old person whose ids moved, and the person that holds them now.
    old: str
    new: str


def _pairs(rows: list[dict[str, Any]], verb: str) -> dict[_Pair, list[dict[str, Any]]]:
    pairs: defaultdict[_Pair, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group = row.get("group") or ""
        old, _, new = group.removeprefix(f"{verb}:").partition(">")
        if not group.startswith(f"{verb}:") or not old or not new:
            continue
        pairs[_Pair(old=old, new=new)].append(row)
    return pairs


def _person_processing_off(team_id: int) -> bool:
    return bool(Team.objects.only("person_processing_opt_out").get(id=team_id).person_processing_opt_out)


def fold(rows: list[dict[str, Any]], context: VerbContext) -> None:
    """Fold a lost person A into the live person B that holds its distinct ids in Postgres.

    Full fold, when A still has a distinct id Postgres has no row for and A or B is identified: restore A with
    those ids, then send $merge_dangerously so ingestion merges A into B (B survives; it takes the earlier
    created_at, and B's properties win over A's). Every merge marks B identified, so a pair where neither is
    identified folds light instead.

    Light fold: send A's ClickHouse-only properties to B as $set_once ($identify when only A is identified).
    A later run that finds them on B points A's ids at B in both stores and tombstones A. B keeps its created_at.

    Neither fold rewrites a diverged id before ingestion confirmed the merge or the properties, so a rescan finds
    any group a run did not finish.
    """
    for row in rows:
        if not (row.get("group") or "").startswith("fold:"):
            context.action(row, "skipped_no_group")
    if _person_processing_off(context.team_id):
        for row in rows:
            context.action(row, "skipped_person_processing_off")
        return
    for pair, group_rows in _pairs(rows, "fold").items():
        repairs._retry_transient(
            partial(_fold_pair, pair, group_rows, context), what=f"fold {pair.old}>{pair.new}", log=context.log
        )


@frozen
class _Survivor:
    properties: dict[str, Any]
    is_identified: bool
    distinct_ids: list[str]


def _survivor(team_id: int, person_uuid: str) -> _Survivor | None:
    persons = get_persons_by_uuids(team_id, [person_uuid], distinct_id_limit=0)
    if not persons:
        return None
    person = persons[0]
    dids = lookups._live_distinct_ids_for_persons(team_id, [person.pk]).get(person.pk) or []
    return _Survivor(
        properties=person.properties or {},
        is_identified=bool(person.is_identified),
        distinct_ids=[d for d, _ in dids],
    )


def _absent_in_postgres(team_id: int, distinct_ids: list[str]) -> list[str]:
    present = (
        {r.distinct_id for r in get_distinct_id_rows(team_id, distinct_ids, strong=True)} if distinct_ids else set()
    )
    return [d for d in distinct_ids if d not in present]


def _fold_pair(pair: _Pair, rows: list[dict[str, Any]], context: VerbContext) -> None:
    old, new = pair.old, pair.new
    person_rows = [r for r in rows if r["kind"] == "person"]
    diverged = [r for r in rows if r["kind"] == "mapping" and r["flavor"] == "diverged"]
    ghosts = [r for r in rows if r["kind"] == "mapping" and r["flavor"] == "ghost"]
    states = observe.pg_person_states(context.team_id, [old, new])
    survivor = _survivor(context.team_id, new) if new in states and not states[new].is_deleted else None
    if survivor is None or (old in states and states[old].is_deleted):
        for row in rows:
            context.action(row, "skipped_changed")
        return
    ghost_ids = _absent_in_postgres(context.team_id, [r["key"] for r in ghosts])
    if old in states:
        # An earlier full fold restored A and stopped before the merge landed: finish A's ids, then send it again.
        absent = [r for r in ghosts if r["key"] in ghost_ids]
        if absent and context.apply:
            _write_mappings(context, absent, {r["key"]: old for r in absent}, "restored")
        _send_fold_merge(context, old, new, [r for r in rows if r not in absent], survivor)
        return
    payload = _live_payloads(context.team_id, [old]).get(old)
    if payload is not None and ghost_ids and (payload.is_identified or survivor.is_identified):
        for row in ghosts:
            if row["key"] not in ghost_ids:
                context.action(row, "skipped_changed")
        live_ghosts = [r for r in ghosts if r["key"] in ghost_ids]
        _full_fold(context, old, new, person_rows, live_ghosts, [*person_rows, *diverged, *live_ghosts], survivor)
    else:
        _light_fold(context, old, new, payload, person_rows, diverged, ghosts, ghost_ids, survivor)


def _full_fold(
    context: VerbContext,
    old: str,
    new: str,
    person_rows: list[dict[str, Any]],
    ghost_rows: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    survivor: _Survivor,
) -> None:
    if not context.apply:
        for row in rows:
            context.action(row, "would_repair", mode="full", target_person=new)
        return
    if old not in _restore_persons(person_rows, context):
        return
    restored_ids = _write_mappings(context, ghost_rows, {r["key"]: old for r in ghost_rows}, "restored")
    if not restored_ids:
        # Ingestion claimed every ghost id between the check and the insert. A stays restored with no distinct id,
        # which the scan reports as no_live_mappings, and its diverged ids stay diverged for a manual repair.
        context.emit_extra(kind="person", key=old, group=f"fold:{old}>{new}", outcome="stopped_no_alias")
        return
    _send_fold_merge(
        context,
        old,
        new,
        [r for r in rows if r["kind"] != "mapping" or r["flavor"] == "diverged"],
        survivor,
        alias=restored_ids[0],
    )


def _send_fold_merge(
    context: VerbContext,
    old: str,
    new: str,
    rows: list[dict[str, Any]],
    survivor: _Survivor,
    alias: str | None = None,
) -> None:
    alias = alias or _any_live_distinct_id(context.team_id, old)
    target = next((d for d in survivor.distinct_ids if d != alias), None)
    if alias is None or target is None or not _owned_on_primary(context.team_id, {alias: old, target: new}):
        for row in rows:
            context.action(row, "skipped_no_alias")
        return
    if not context.apply:
        for row in rows:
            context.action(row, "would_repair", mode="merge", target_person=new)
        return
    outcome = _send_merge(context, distinct_id=target, alias=alias)
    _report_merge(context, old, new, f"fold:{old}>{new}", rows, outcome)


def _report_merge(
    context: VerbContext, old: str, new: str, group: str, rows: list[dict[str, Any]], outcome: str
) -> None:
    for row in rows:
        if row["kind"] == "person":
            context.action(row, outcome, survivor=new)
        else:
            context.action(row, "awaiting_merge" if outcome == "merge_sent" else outcome, target_person=new)
    if not any(r["kind"] == "person" and r["key"] == old for r in rows):
        context.emit_extra(kind="person", key=old, group=group, outcome=outcome, survivor=new)


def _owned_on_primary(team_id: int, owners: dict[str, str]) -> bool:
    """Whether each distinct id maps to the given person on the primary, so the event merges the intended pair."""
    rows = {r.distinct_id: r for r in get_distinct_id_rows(team_id, list(owners), strong=True)}
    return all(
        (row := rows.get(d)) is not None and not row.is_deleted and row.person_uuid == u for d, u in owners.items()
    )


def _light_fold(
    context: VerbContext,
    old: str,
    new: str,
    payload: _Payload | None,
    person_rows: list[dict[str, Any]],
    diverged: list[dict[str, Any]],
    ghosts: list[dict[str, Any]],
    ghost_ids: list[str],
    survivor: _Survivor,
) -> None:
    for row in ghosts:
        if row["key"] not in ghost_ids:
            # Its id has a Postgres row now; the next scan names its new state.
            context.action(row, "skipped_changed")
    moving = [*diverged, *(r for r in ghosts if r["key"] in ghost_ids)]
    missing = {k: v for k, v in (payload.properties if payload else {}).items() if k not in survivor.properties}
    # A same-person $identify needs two of B's ids; with one, B cannot be marked identified by an event.
    identify = bool(payload and payload.is_identified and not survivor.is_identified and len(survivor.distinct_ids) > 1)
    if missing or identify:
        if not context.apply:
            for row in [*person_rows, *moving]:
                context.action(row, "would_repair", mode="light", target_person=new, set_once_keys=len(missing))
            return
        context.pacer.before_write()
        refusal = _send_light_fold_event(context, survivor, missing, identify)
        for row in [*person_rows, *moving]:
            context.action(row, refusal or "properties_sent", target_person=new, set_once_keys=len(missing))
        return
    if not context.apply:
        for row in [*person_rows, *moving]:
            context.action(row, "would_repair", mode="light", target_person=new)
        return
    # B holds A's properties now. Burying A first means a run stopped here leaves diverged ids, which a rescan
    # reports as a fold with nothing left to carry, rather than a ghost of A that restore could revive.
    orphans = find_orphaned_ch_persons(context.team_id, [old]) if payload is not None else []
    if orphans:
        context.pacer.before_write()
        tombstone_orphaned_ch_persons(context.team_id, orphans, dry_run=False)
    _write_mappings(context, moving, {r["key"]: new for r in moving}, "moved")
    for row in person_rows:
        context.action(row, "folded", target_person=new, buried=bool(orphans))


def _send_light_fold_event(
    context: VerbContext, survivor: _Survivor, missing: dict[str, Any], identify: bool
) -> str | None:
    distinct_id = survivor.distinct_ids[0] if survivor.distinct_ids else None
    if distinct_id is None:
        return "skipped_no_distinct_id"
    if not identify:
        return stale_merge.send_set_once(
            context.team_id, distinct_id, missing, survivor.properties, event_source="person_consistency_fold"
        )
    # Both ids already belong to B, so ingestion merges nothing and only marks B identified and applies $set_once.
    return stale_merge.send_set_once(
        context.team_id,
        distinct_id,
        missing,
        survivor.properties,
        event_source="person_consistency_fold",
        event_name="$identify",
        extra_properties={"$anon_distinct_id": survivor.distinct_ids[1]},
    )


def _send_merge(context: VerbContext, *, distinct_id: str, alias: str) -> str:
    """Send $merge_dangerously on B's distinct id, so B survives and ingestion merges the alias's person into it."""
    context.pacer.before_write()
    token = Team.objects.only("api_token").get(id=context.team_id).api_token
    try:
        capture_internal(
            token=token,
            event_name="$merge_dangerously",
            event_source=f"person_consistency_{context.verb}",
            distinct_id=distinct_id,
            timestamp=datetime.now(UTC),
            properties={"alias": alias},
            process_person_profile=True,
        ).raise_for_status()
    except Exception:
        return "skipped_merge_failed"
    return "merge_sent"


def _any_live_distinct_id(team_id: int, person_uuid: str) -> str | None:
    persons = get_persons_by_uuids(team_id, [person_uuid], distinct_id_limit=0)
    if not persons:
        return None
    dids = lookups._live_distinct_ids_for_persons(team_id, [persons[0].pk]).get(persons[0].pk) or []
    return dids[0][0] if dids else None


def merge(rows: list[dict[str, Any]], context: VerbContext) -> None:
    """Merge a live old person A into the live person B that holds A's distinct ids in Postgres, through ingestion:
    send $merge_dangerously on a B id with an A id as the alias, so B survives.

    The diverged ids stay as they are until ingestion merged A: a later scan then reports them for republish, or
    reports the merge again if it did not land.
    """
    for row in rows:
        if not (row.get("group") or "").startswith("merge:"):
            context.action(row, "skipped_no_group")
    if _person_processing_off(context.team_id):
        for row in rows:
            context.action(row, "skipped_person_processing_off")
        return
    for pair, group_rows in _pairs(rows, "merge").items():
        old, new = pair.old, pair.new
        states = observe.pg_person_states(context.team_id, [old, new])
        if any(u not in states or states[u].is_deleted for u in (old, new)):
            for row in group_rows:
                context.action(row, "skipped_changed")
            continue
        alias = _any_live_distinct_id(context.team_id, old)
        target = next(
            (
                r["key"]
                for r in group_rows
                if r["kind"] == "mapping" and (r["evidence"]["pg"] or {}).get("person_uuid") == new
            ),
            None,
        )
        if alias is None or target is None or not _owned_on_primary(context.team_id, {alias: old, target: new}):
            for row in group_rows:
                context.action(row, "skipped_no_alias")
            continue
        if not context.apply:
            for row in group_rows:
                context.action(row, "would_repair", target_person=new)
            continue
        outcome = repairs._retry_transient(
            partial(_send_merge, context, distinct_id=target, alias=alias), what=f"merge {old}>{new}", log=context.log
        )
        _report_merge(context, old, new, group_rows[0]["group"], group_rows, outcome)
