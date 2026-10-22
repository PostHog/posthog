"""Repair verbs that rebuild Postgres from ClickHouse: restore a lost person with its distinct ids, fold a lost
person into the person that holds its distinct ids now, or merge two live persons through ingestion."""

from __future__ import annotations

import json
import time
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
    RESTORE_OUTCOME_NO_DISTINCT_ID,
    DistinctIdWrite,
    RestoredDistinctId,
    RestoredPerson,
    RestorePersonsRequest,
    WriteDistinctIdsRequest,
)

from . import lookups, observe, repairs, stale_merge

if TYPE_CHECKING:
    from .verbs import VerbContext

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
    for batch in lookups._chunks(rows, repairs._WRITE_BATCH_SIZE):
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
                    ),
                    repairs.PublishedKey(kind="mapping", key=result.distinct_id),
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
    """Insert lost persons into Postgres from their ClickHouse winner, one version above ClickHouse, together with
    their lost distinct ids, and publish both. A person or mapping that exists again in Postgres is left alone."""
    mapping_rows = [r for r in rows if r["kind"] == "mapping"]
    person_rows = [r for r in rows if r["kind"] == "person"]
    outcome = _restore_persons(person_rows, mapping_rows, context)
    rest = [r for r in mapping_rows if r["key"] not in outcome.handled_ids]
    _write_mappings(context, rest, {r["key"]: r["evidence"]["ch"]["winner_person_uuid"] for r in rest}, "restored")


@frozen
class _RestoreOutcome:
    restored: dict[str, list[str]]
    handled_ids: frozenset[str]


def _restore_persons(
    rows: list[dict[str, Any]], mapping_rows: list[dict[str, Any]], context: VerbContext
) -> _RestoreOutcome:
    """Restore each person with the lost distinct ids ClickHouse gives it, in one personhog call per batch.
    A person none of whose ids can be restored is not inserted, so nothing ends up live and unreachable."""
    ids_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mapping_rows:
        if row["evidence"]["pg"] is None:
            ids_by_owner[row["evidence"]["ch"]["winner_person_uuid"]].append(row)
    restored: dict[str, list[str]] = {}
    handled: set[str] = set()
    for batch in lookups._chunks(rows, repairs._WRITE_BATCH_SIZE):
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
            elif not ids_by_owner.get(person_uuid):
                # Restored alone, the person would have no distinct id, so nothing could reach it.
                context.action(row, "skipped_no_distinct_id")
            else:
                candidates.append(person_uuid)
        if not candidates:
            continue
        id_rows = {u: ids_by_owner[u] for u in candidates}
        handled.update(r["key"] for u in candidates for r in id_rows[u])
        if not context.apply:
            for person_uuid in candidates:
                for row in [by_uuid[person_uuid], *id_rows[person_uuid]]:
                    context.action(row, "would_repair", target_version=payloads[person_uuid].max_version + 1)
            continue
        ch = observe.ch_mapping_states(context.team_id, [r["key"] for u in candidates for r in id_rows[u]])
        versions = {key: (state.max_version + 1) for key, state in ch.items()}
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
                    distinct_ids=[
                        RestoredDistinctId(distinct_id=r["key"], version=versions.get(r["key"], 0)) for r in id_rows[u]
                    ],
                )
                for u in candidates
            ],
        )
        response = personhog_call(
            "person_consistency_restore_persons", partial(require_personhog_client().restore_persons, request)
        )
        for result in response.results:
            row = by_uuid[result.person_uuid]
            ids = list(result.restored_distinct_ids)
            if result.outcome == RESTORE_OUTCOME_INSERTED:
                # A person whose publish does not land is recorded undelivered; it then exists in Postgres, so the
                # next scan reports it as behind ClickHouse, and republish publishes it.
                context.deliveries.track(
                    _publish_person(
                        context.team_id, result.person_uuid, payloads[result.person_uuid], int(result.version)
                    ),
                    repairs.PublishedKey(kind="person", key=result.person_uuid),
                )
                for distinct_id in ids:
                    context.deliveries.track(
                        create_person_distinct_id(
                            context.team_id, distinct_id, result.person_uuid, version=versions.get(distinct_id, 0)
                        ),
                        repairs.PublishedKey(kind="mapping", key=distinct_id),
                    )
                restored[result.person_uuid] = ids
                context.action(row, "restored", version=int(result.version))
            elif result.outcome == RESTORE_OUTCOME_NO_DISTINCT_ID:
                context.action(row, "skipped_no_distinct_id")
            else:
                live = result.outcome == RESTORE_OUTCOME_EXISTS_LIVE
                context.action(row, "skipped_exists_live" if live else "skipped_exists_tombstoned")
            for id_row in id_rows[result.person_uuid]:
                if id_row["key"] in ids:
                    context.action(
                        id_row, "restored", target_person=result.person_uuid, version=versions.get(id_row["key"], 0)
                    )
                else:
                    # Claimed since the scan, or its person was not inserted: the next scan names its new state.
                    context.action(id_row, "skipped_changed", target_person=result.person_uuid)
    return _RestoreOutcome(restored=restored, handled_ids=frozenset(handled))


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

    Full fold, when A has an id Postgres lacks and A or B is identified: restore A with those ids, merge it into B
    through ingestion, then point A's diverged ids at B. Otherwise light fold, because every merge marks B
    identified: send A's ClickHouse-only properties to B, and a later run moves A's ids to B and tombstones A.
    """
    for row in rows:
        if not (row.get("group") or "").startswith("fold:"):
            context.action(row, "skipped_no_group")
    if _person_processing_off(context.team_id):
        for row in rows:
            context.action(row, "skipped_person_processing_off")
        return
    pending: list[_PendingMerge] = []
    for pair, group_rows in _pairs(rows, "fold").items():
        sent = repairs._retry_transient(
            partial(_fold_pair, pair, group_rows, context), what=f"fold {pair.old}>{pair.new}", log=context.log
        )
        if sent is not None:
            pending.append(sent)
    _confirm_merges(context, pending, done="folded")


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


def _fold_pair(pair: _Pair, rows: list[dict[str, Any]], context: VerbContext) -> _PendingMerge | None:
    old, new = pair.old, pair.new
    person_rows = [r for r in rows if r["kind"] == "person"]
    diverged = [r for r in rows if r["kind"] == "mapping" and r["flavor"] == "diverged"]
    ghosts = [r for r in rows if r["kind"] == "mapping" and r["flavor"] == "ghost"]
    states = observe.pg_person_states(context.team_id, [old, new])
    survivor = _survivor(context.team_id, new) if new in states and not states[new].is_deleted else None
    if survivor is None or (old in states and states[old].is_deleted):
        for row in rows:
            context.action(row, "skipped_changed")
        return None
    ghost_ids = _absent_in_postgres(context.team_id, [r["key"] for r in ghosts])
    if old in states:
        # An earlier full fold restored A and stopped before the merge landed: finish A's ids, then send it again.
        absent = [r for r in ghosts if r["key"] in ghost_ids]
        if absent and context.apply:
            _write_mappings(context, absent, {r["key"]: old for r in absent}, "restored")
        return _send_fold_merge(context, old, new, [r for r in rows if r not in absent], survivor)
    payload = _live_payloads(context.team_id, [old]).get(old)
    if payload is not None and ghost_ids and (payload.is_identified or survivor.is_identified):
        for row in ghosts:
            if row["key"] not in ghost_ids:
                context.action(row, "skipped_changed")
        live_ghosts = [r for r in ghosts if r["key"] in ghost_ids]
        return _full_fold(
            context, old, new, person_rows, live_ghosts, [*person_rows, *diverged, *live_ghosts], survivor
        )
    _light_fold(context, old, new, payload, person_rows, diverged, ghosts, ghost_ids, survivor)
    return None


def _full_fold(
    context: VerbContext,
    old: str,
    new: str,
    person_rows: list[dict[str, Any]],
    ghost_rows: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    survivor: _Survivor,
) -> _PendingMerge | None:
    if not context.apply:
        for row in rows:
            context.action(row, "would_repair", mode="full", target_person=new)
        return None
    restored_ids = _restore_persons(person_rows, ghost_rows, context).restored.get(old)
    if not restored_ids:
        # A exists again, or every ghost id was claimed since the scan: the next scan names its new state.
        return None
    return _send_fold_merge(
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
) -> _PendingMerge | None:
    alias = alias or _any_live_distinct_id(context.team_id, old)
    target = next((d for d in survivor.distinct_ids if d != alias), None)
    if alias is None or target is None or not _owned_on_primary(context.team_id, {alias: old, target: new}):
        for row in rows:
            context.action(row, "skipped_no_alias")
        return None
    if not context.apply:
        for row in rows:
            context.action(row, "would_repair", mode="merge", target_person=new)
        return None
    outcome = _send_merge(context, distinct_id=target, alias=alias)
    group = f"fold:{old}>{new}"
    if outcome == "merge_sent":
        return _PendingMerge(old=old, new=new, group=group, rows=rows)
    _report_merge(context, old, new, group, rows, outcome)
    return None


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
    needs_identified = bool(payload and payload.is_identified and not survivor.is_identified)
    identify = needs_identified and len(survivor.distinct_ids) > 1
    carry = {"identified_not_carried": True} if needs_identified and not identify else {}
    if missing or identify:
        if not context.apply:
            for row in [*person_rows, *moving]:
                context.action(
                    row, "would_repair", mode="light", target_person=new, set_once_keys=len(missing), **carry
                )
            return
        context.pacer.before_write()
        refusal = _send_light_fold_event(context, survivor, missing, identify)
        for row in [*person_rows, *moving]:
            context.action(row, refusal or "properties_sent", target_person=new, set_once_keys=len(missing), **carry)
        return
    if not context.apply:
        for row in [*person_rows, *moving]:
            context.action(row, "would_repair", mode="light", target_person=new)
        return
    # Move A's Postgres-less ids before burying A, because a rescan then treats them as a deleted person's ids.
    # The diverged ids move last, so a run stopped at any step leaves only ids that republish fixes.
    absent = [r for r in moving if r["flavor"] == "ghost"]
    _write_mappings(context, absent, {r["key"]: new for r in absent}, "moved")
    orphans = find_orphaned_ch_persons(context.team_id, [old]) if payload is not None else []
    if orphans:
        context.pacer.before_write()
        tombstone_orphaned_ch_persons(context.team_id, orphans, dry_run=False)
    _write_mappings(context, diverged, {r["key"]: new for r in diverged}, "moved")
    for row in person_rows:
        context.action(row, "folded", target_person=new, buried=bool(orphans), **carry)


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


# Ingestion applies a merge within seconds, so a merge still pending after this wait is left for the next scan.
_MERGE_CONFIRM_SECONDS = 60.0
_MERGE_POLL_MAX_SECONDS = 8.0
_sleep = time.sleep
_monotonic = time.monotonic


@frozen
class _PendingMerge:
    old: str
    new: str
    group: str
    rows: list[dict[str, Any]]


def _confirm_merges(context: VerbContext, pending: list[_PendingMerge], *, done: str) -> None:
    """Wait for ingestion to merge each old person away, then point its diverged ids at the survivor.

    A merge that has not landed by the deadline leaves its ids diverged, so the next scan finds the group again.
    """
    deadline = _monotonic() + _MERGE_CONFIRM_SECONDS
    wait = 1.0
    while pending:
        _sleep(wait)
        wait = min(wait * 2, _MERGE_POLL_MAX_SECONDS)
        states = repairs._retry_transient(
            partial(observe.pg_person_states, context.team_id, [p.old for p in pending]),
            what="merge confirm",
            log=context.log,
        )
        landed = [p for p in pending if p.old not in states or states[p.old].is_deleted]
        for merge in landed:
            repairs._retry_transient(
                partial(_finish_merge, context, merge, done), what=f"finish {merge.old}>{merge.new}", log=context.log
            )
        pending = [p for p in pending if p not in landed]
        if _monotonic() >= deadline:
            break
    for merge in pending:
        _report_merge(context, merge.old, merge.new, merge.group, merge.rows, "merge_sent")


def _finish_merge(context: VerbContext, merge: _PendingMerge, done: str) -> None:
    diverged = [r for r in merge.rows if r["kind"] == "mapping" and r["flavor"] == "diverged"]
    _write_mappings(context, diverged, {r["key"]: merge.new for r in diverged}, "moved")
    for row in merge.rows:
        if row["kind"] == "person":
            context.action(row, done, survivor=merge.new)
        elif row not in diverged:
            context.action(row, done, target_person=merge.new)
    if not any(r["kind"] == "person" and r["key"] == merge.old for r in merge.rows):
        context.emit_extra(kind="person", key=merge.old, group=merge.group, outcome=done, survivor=merge.new)


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
    """Merge a live old person A into B, which holds A's ids in Postgres, with $merge_dangerously on a B id.

    The diverged ids move to B once ingestion merged A.
    """
    for row in rows:
        if not (row.get("group") or "").startswith("merge:"):
            context.action(row, "skipped_no_group")
    if _person_processing_off(context.team_id):
        for row in rows:
            context.action(row, "skipped_person_processing_off")
        return
    pending: list[_PendingMerge] = []
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
        if outcome == "merge_sent":
            pending.append(_PendingMerge(old=old, new=new, group=group_rows[0]["group"], rows=group_rows))
        else:
            _report_merge(context, old, new, group_rows[0]["group"], group_rows, outcome)
    _confirm_merges(context, pending, done="merged")
