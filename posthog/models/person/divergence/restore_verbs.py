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

from . import lookups, observe, stale_merge

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
    person_rows = [r for r in rows if r["kind"] == "person"]
    restored = _restore_persons(person_rows, context)
    mapping_rows = [r for r in rows if r["kind"] == "mapping"]
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
    """Fold a lost person A into the live person B that holds its distinct ids in Postgres: point A's distinct
    ids at B in both stores, send A's ClickHouse-only properties to B as $set_once, then tombstone A.

    B keeps its own created_at; only ingestion's merge moves it to the earlier of the two.
    """
    for row in rows:
        if not (row.get("group") or "").startswith("fold:"):
            context.action(row, "skipped_no_group")
    if _person_processing_off(context.team_id):
        for row in rows:
            context.action(row, "skipped_person_processing_off")
        return
    for pair, group_rows in _pairs(rows, "fold").items():
        _fold_pair(pair.old, pair.new, group_rows, context)


def _fold_pair(old: str, new: str, rows: list[dict[str, Any]], context: VerbContext) -> None:
    states = observe.pg_person_states(context.team_id, [old, new])
    person_rows = [r for r in rows if r["kind"] == "person"]
    mapping_rows = [r for r in rows if r["kind"] == "mapping"]
    if old in states or new not in states or states[new].is_deleted:
        for row in rows:
            context.action(row, "skipped_changed")
        return
    moved = _write_mappings(context, mapping_rows, {r["key"]: new for r in mapping_rows}, "moved")
    if not context.apply:
        for row in person_rows:
            context.action(row, "would_repair", target_person=new)
        return
    payload = _live_payloads(context.team_id, [old]).get(old)
    if payload is None:
        for row in person_rows:
            context.action(row, "skipped_not_divergent")
        return
    survivor = get_persons_by_uuids(context.team_id, [new], distinct_id_limit=0)
    existing = (survivor[0].properties or {}) if survivor else {}
    missing = {k: v for k, v in payload.properties.items() if k not in existing}
    if missing:
        distinct_id = moved[0] if moved else _any_live_distinct_id(context.team_id, new)
        refusal = (
            "skipped_no_distinct_id"
            if distinct_id is None
            else stale_merge.send_set_once(
                context.team_id, distinct_id, missing, existing, event_source="person_consistency_fold"
            )
        )
        if refusal is not None:
            # A keeps its ClickHouse copy until its properties reach B.
            for row in person_rows:
                context.action(row, refusal, target_person=new)
            return
    orphans = find_orphaned_ch_persons(context.team_id, [old])
    tombstone_orphaned_ch_persons(context.team_id, orphans, dry_run=False)
    for row in person_rows:
        context.action(row, "folded", target_person=new, set_once_keys=len(missing), buried=bool(orphans))


def _any_live_distinct_id(team_id: int, person_uuid: str) -> str | None:
    persons = get_persons_by_uuids(team_id, [person_uuid], distinct_id_limit=0)
    if not persons:
        return None
    dids = lookups._live_distinct_ids_for_persons(team_id, [persons[0].pk]).get(persons[0].pk) or []
    return dids[0][0] if dids else None


def merge(rows: list[dict[str, Any]], context: VerbContext) -> None:
    """Merge a live old person A into the live person B that holds A's distinct ids in Postgres: point those
    ids at B in both stores, then send $merge_dangerously so ingestion merges A into B, with B surviving."""
    for row in rows:
        if not (row.get("group") or "").startswith("merge:"):
            context.action(row, "skipped_no_group")
    if _person_processing_off(context.team_id):
        for row in rows:
            context.action(row, "skipped_person_processing_off")
        return
    token = Team.objects.only("api_token").get(id=context.team_id).api_token
    for pair, group_rows in _pairs(rows, "merge").items():
        old, new = pair.old, pair.new
        states = observe.pg_person_states(context.team_id, [old, new])
        if any(u not in states or states[u].is_deleted for u in (old, new)):
            for row in group_rows:
                context.action(row, "skipped_changed")
            continue
        alias = _any_live_distinct_id(context.team_id, old)
        if alias is None:
            for row in group_rows:
                context.action(row, "skipped_no_alias")
            continue
        moved = _write_mappings(context, group_rows, {r["key"]: new for r in group_rows}, "moved")
        if not context.apply or not moved:
            continue
        # The event's distinct id belongs to B, so B survives; ingestion moves A's ids and deletes A.
        try:
            capture_internal(
                token=token,
                event_name="$merge_dangerously",
                event_source="person_consistency_merge",
                distinct_id=moved[0],
                timestamp=datetime.now(UTC),
                properties={"alias": alias},
                process_person_profile=True,
            ).raise_for_status()
            outcome = "merge_sent"
        except Exception:
            outcome = "skipped_merge_failed"
        context.emit_extra(kind="person", key=old, group=group_rows[0]["group"], outcome=outcome, survivor=new)
