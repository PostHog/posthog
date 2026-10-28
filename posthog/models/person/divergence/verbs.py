"""Repair verbs. Each takes the report rows of a team scan that name it, re-checks every key against the current
state, and writes only what still applies. Every verb is a dry run unless applied, and every write only raises a
version or acts on the exact state it read, so a rerun repeats nothing."""

from __future__ import annotations

import json
import signal
import threading
import dataclasses
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.person.deletion import (
    count_live_ch_persons,
    find_orphaned_ch_persons,
    orphan_share_refusal,
    tombstone_orphaned_ch_persons,
)
from posthog.models.person.util import create_person_distinct_id, get_distinct_id_rows, get_persons_by_uuids
from posthog.personhog_client.proto import DistinctIdRow

from . import datatypes, lookups, observe, repairs, restore_verbs, team_scan

# A key whose last recorded outcome is one of these needs nothing more, so a resumed run skips it.
DONE_OUTCOMES = frozenset(
    {
        "repaired",
        "tombstoned",
        "republished",
        "buried",
        "restored",
        "already_restored",
        "moved",
        "already_moved",
        "folded",
        "merged",
    }
)


class VerbError(Exception):
    pass


@frozen
class RowKey:
    kind: str
    key: str


@frozen
class VerbAction:
    verb: str
    team_id: int
    kind: str
    key: str
    group: str | None
    outcome: str
    detail: dict[str, Any]


@frozen(frozen=False)
class VerbContext:
    verb: str
    team_id: int
    apply: bool
    force: bool
    max_calls_per_second: float | None
    log: Callable[[str], None]
    emit: Callable[[VerbAction], None]
    pacer: repairs._WritePacer
    deliveries: repairs._Deliveries

    def action(self, row: dict[str, Any], outcome: str, **detail: Any) -> None:
        self.emit(
            VerbAction(
                verb=self.verb,
                team_id=self.team_id,
                kind=row["kind"],
                key=row["key"],
                group=row.get("group"),
                outcome=outcome,
                detail=detail,
            )
        )

    def emit_extra(self, *, kind: str, key: str, group: str | None, outcome: str, **detail: Any) -> None:
        """Record an action on a key the report has no row for, such as the old person of a merge."""
        self.emit(
            VerbAction(
                verb=self.verb, team_id=self.team_id, kind=kind, key=key, group=group, outcome=outcome, detail=detail
            )
        )


VerbFn = Callable[[list[dict[str, Any]], VerbContext], None]


def load_rows(
    scan_dir: Path,
    verb: str,
    *,
    groups: Sequence[str] = (),
    keys: Sequence[str] = (),
    limit: int | None = None,
    skip: Iterable[RowKey] = (),
    pairs: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The report rows that name `verb`, optionally only those in `groups` or with `keys`, at most `limit`.

    Each of `pairs` ("A>B") names an old person A and the live person B to fold or merge it into, which the scan
    leaves ambiguous when A's distinct ids went to more than one person. It selects A's person row, A's ghost
    mappings and the mappings that moved from A to B, whatever their verb, as one group of `verb`.
    """
    path = scan_dir / team_scan.REPORT_FILE
    if not path.exists():
        raise VerbError(f"{path} does not exist; finalize the scan first")
    wanted_groups, wanted_keys, skipped = set(groups), set(keys), set(skip)
    chosen = _parse_pairs(verb, pairs)
    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line in handle:
            row = json.loads(line)
            if RowKey(kind=row["kind"], key=row["key"]) in skipped:
                continue
            if chosen:
                group = _pair_group(row, chosen, verb)
                if group is None:
                    continue
                row = {**row, "verb": verb, "group": group}
            elif row["verb"] != verb:
                continue
            if wanted_groups and row["group"] not in wanted_groups:
                continue
            if wanted_keys and row["key"] not in wanted_keys:
                continue
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _parse_pairs(verb: str, pairs: Sequence[str]) -> dict[str, str]:
    if pairs and verb not in ("fold", "merge"):
        raise VerbError("--pair applies to fold and merge only")
    chosen: dict[str, str] = {}
    for pair in pairs:
        old, sep, new = pair.partition(">")
        if not sep or not old or not new or old == new:
            raise VerbError(f"--pair {pair!r} must be OLD_UUID>NEW_UUID")
        if old in chosen:
            raise VerbError(f"--pair names {old} twice; fold or merge a person into one survivor")
        chosen[old] = new
    return chosen


def _pair_group(row: dict[str, Any], chosen: dict[str, str], verb: str) -> str | None:
    if row["kind"] == "person":
        old = row["key"] if row["key"] in chosen else None
    else:
        ch_owner = ((row.get("evidence") or {}).get("ch") or {}).get("winner_person_uuid")
        pg_owner = ((row.get("evidence") or {}).get("pg") or {}).get("person_uuid")
        moved = row["flavor"] == "diverged" and ch_owner in chosen and pg_owner == chosen[ch_owner]
        old = ch_owner if moved or (row["flavor"] == "ghost" and ch_owner in chosen) else None
    return None if old is None else f"{verb}:{old}>{chosen[old]}"


def done_keys(actions_path: Path) -> set[RowKey]:
    """Keys whose last recorded outcome in an actions file needs nothing more."""
    last: dict[RowKey, str] = {}
    if actions_path.exists():
        with actions_path.open() as handle:
            for line in handle:
                action = json.loads(line)
                last[RowKey(kind=action["kind"], key=action["key"])] = action["outcome"]
    return {key for key, outcome in last.items() if outcome in DONE_OUTCOMES}


def run_verb(
    scan_dir: Path,
    verb: str,
    *,
    apply: bool,
    actions_path: Path,
    resume: bool = False,
    groups: Sequence[str] = (),
    keys: Sequence[str] = (),
    limit: int | None = None,
    max_calls_per_second: float | None = None,
    force: bool = False,
    pairs: Sequence[str] = (),
    log: Callable[[str], None] = lambda _: None,
) -> Counter[str]:
    """Run one verb over the scan's report rows and append one action per key to `actions_path`.

    With `resume`, keys that `actions_path` already records as done are skipped. Returns counts by outcome.
    """
    if verb not in VERBS:
        raise VerbError(f"unknown verb {verb}; choose one of {', '.join(sorted(VERBS))}")
    if actions_path.exists() and not resume:
        raise VerbError(f"{actions_path} exists; pass --resume to continue it")
    plan = team_scan.load_plan(scan_dir)
    if not plan.team_exists:
        raise VerbError(f"team {plan.team_id} does not exist; there is nothing to repair")
    rows = load_rows(scan_dir, verb, groups=groups, keys=keys, limit=limit, skip=done_keys(actions_path), pairs=pairs)
    counts: Counter[str] = Counter()
    with actions_path.open("a") as out:

        def emit(action: VerbAction) -> None:
            out.write(json.dumps({**_asdict(action), "applied": apply, "at": datetime.now(UTC).isoformat()}) + "\n")
            out.flush()
            counts[action.outcome] += 1

        context = VerbContext(
            verb=verb,
            team_id=plan.team_id,
            apply=apply,
            force=force,
            max_calls_per_second=max_calls_per_second,
            log=log,
            emit=emit,
            pacer=repairs._WritePacer(max_per_second=max_calls_per_second),
            deliveries=repairs._Deliveries(),
        )
        log(f"{verb}: {len(rows)} rows, {'APPLY' if apply else 'DRY RUN'}")
        terminated = False

        def on_sigterm(_signum: int, _frame: Any) -> None:
            nonlocal terminated
            terminated = True
            raise SystemExit(128 + signal.SIGTERM)

        restore_sigterm = _handle_sigterm(on_sigterm)
        try:
            if rows:
                VERBS[verb](rows, context)
        finally:
            restore_sigterm()
            if apply:
                undelivered = context.deliveries.undelivered(
                    _TERMINATION_FLUSH_SECONDS if terminated else repairs._FLUSH_TIMEOUT_SECONDS
                )
                if undelivered:
                    # A key whose publish did not land gets a last action that is not done, so resume retries it.
                    by_key = {RowKey(kind=r["kind"], key=r["key"]): r for r in rows}
                    for key in context.deliveries.undelivered_keys():
                        row = by_key.get(RowKey(kind=key.kind, key=key.key)) or {
                            "kind": key.kind,
                            "key": key.key,
                            "group": None,
                        }
                        context.action(row, "undelivered")
                    counts["undelivered"] += undelivered - len(context.deliveries.undelivered_keys())
                    log(f"{verb}: {undelivered} ClickHouse messages were not delivered; rerun with --resume")
    return counts


# Kubernetes sends SIGKILL a grace period after SIGTERM, so the final flush must finish well inside it.
_TERMINATION_FLUSH_SECONDS = 20.0


def _handle_sigterm(handler: Callable[[int, Any], None]) -> Callable[[], None]:
    """Run `handler` on SIGTERM until the returned callable restores the previous handler.

    A toolbox pod that is deleted or redeployed gets SIGTERM, which by default ends the process without running
    `finally`, so its undelivered keys would be recorded as done. Signals only reach the main thread.
    """
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    previous = signal.signal(signal.SIGTERM, handler)

    def restore() -> None:
        signal.signal(signal.SIGTERM, previous)

    return restore


def _collect_outcome(sink: list[tuple[str, str]], person_uuid: str, outcome: str) -> None:
    sink.append((person_uuid, outcome))


def _asdict(action: VerbAction) -> dict[str, Any]:
    return dataclasses.asdict(action)


def _from_repair_action(
    context: VerbContext, rows_by_key: dict[str, dict[str, Any]], a: datatypes.RepairAction
) -> None:
    key = a.distinct_id or a.person_uuid
    row = rows_by_key.get(key) or {"kind": "mapping" if a.distinct_id else "person", "key": key, "group": None}
    context.action(
        row,
        a.outcome,
        person_uuid=a.person_uuid,
        divergence=a.kind,
        pg_version=a.pg_version,
        ch_max_version=a.ch_max_version,
        target_version=a.target_version,
    )


def _republish_persons(
    rows: list[dict[str, Any]],
    context: VerbContext,
    person_uuids: list[str],
    *,
    republish_equal: Iterable[str] = (),
    stale_merge_distinct_ids: dict[str, str] | None = None,
) -> None:
    rows_by_key = {row["key"]: row for row in rows}
    repairs.repair_persons(
        [datatypes.PersonRef(team_id=context.team_id, person_uuid=u) for u in dict.fromkeys(person_uuids)],
        apply=context.apply,
        max_writes_per_second=context.max_calls_per_second,
        on_action=lambda a: _from_repair_action(context, rows_by_key, a),
        log=context.log,
        republish_equal=frozenset(republish_equal),
        stale_merge_distinct_ids=stale_merge_distinct_ids,
        deliveries=context.deliveries,
    )


def republish(rows: list[dict[str, Any]], context: VerbContext) -> None:
    """Raise Postgres above ClickHouse and publish the Postgres state: hidden, swept, behind, missing, tied and
    blanked persons, and stale, hidden, missing or diverged mappings, through their Postgres owner."""
    person_uuids: list[str] = []
    for row in rows:
        if row["kind"] == "person":
            person_uuids.append(row["key"])
            continue
        owner = (row["evidence"]["pg"] or {}).get("person_uuid")
        if owner is None:
            context.action(row, "skipped_no_owner")
        else:
            person_uuids.append(owner)
    equal = [r["key"] for r in rows if r["kind"] == "person" and r["flavor"] in ("tie", "blanked")]
    _republish_persons(rows, context, person_uuids, republish_equal=equal)


def merge_stale(rows: list[dict[str, Any]], context: VerbContext) -> None:
    """Send each stale person's ClickHouse-only properties to ingestion as $set_once.

    Run it again once ingestion applied them: a person with nothing left to send is then raised and republished.
    """
    person_rows = [r for r in rows if r["kind"] == "person"]
    persons = get_persons_by_uuids(context.team_id, [r["key"] for r in person_rows], distinct_id_limit=0)
    pk_by_uuid = {str(p.uuid): p.pk for p in persons}
    distinct_ids = lookups._live_distinct_ids_for_persons(context.team_id, list(pk_by_uuid.values()))
    merge_ids: dict[str, str] = {}
    for row in person_rows:
        dids = distinct_ids.get(pk_by_uuid.get(row["key"], -1)) or []
        if dids:
            merge_ids[row["key"]] = dids[0][0]
        else:
            context.action(row, "skipped_no_distinct_id")
    _republish_persons(rows, context, list(merge_ids), stale_merge_distinct_ids=merge_ids)


def bury(rows: list[dict[str, Any]], context: VerbContext) -> None:
    """Tombstone persons and mappings that Postgres deleted but ClickHouse still shows, one version above
    ClickHouse in both stores."""
    person_rows = [r for r in rows if r["kind"] == "person"]
    if person_rows:
        _bury_persons(person_rows, context)
    for row in rows:
        if row["kind"] == "mapping":
            repairs._retry_transient(partial(_bury_mapping, row, context), what="bury mapping", log=context.log)


def _bury_persons(rows: list[dict[str, Any]], context: VerbContext) -> None:
    by_uuid = {row["key"]: row for row in rows}
    orphans = find_orphaned_ch_persons(context.team_id, list(by_uuid))
    orphaned = {o.uuid for o in orphans}
    for person_uuid, row in by_uuid.items():
        if person_uuid not in orphaned:
            # Live in Postgres, or no longer live in ClickHouse.
            context.action(row, "skipped_not_divergent")
    if not orphans:
        return
    if not context.apply:
        for orphan in orphans:
            context.action(by_uuid[orphan.uuid], "would_repair", ch_max_version=orphan.ch_max_version)
        return
    planned = tombstone_orphaned_ch_persons(context.team_id, orphans, dry_run=True)
    if planned.tombstoned_persons and not context.force:
        refusal = orphan_share_refusal(
            context.team_id, planned.tombstoned_persons, count_live_ch_persons(context.team_id)
        )
        if refusal is not None:
            context.log(refusal)
            for orphan in orphans:
                context.action(by_uuid[orphan.uuid], "skipped_share_limit")
            return
    # The orphan repair reports an outcome before it publishes and raises when a publish fails, so outcomes are
    # recorded only once every publish landed; otherwise each key is recorded as undelivered for resume to retry.
    for chunk in lookups._chunks(orphans, repairs._WRITE_BATCH_SIZE):
        outcomes: list[tuple[str, str]] = []
        context.pacer.before_write()
        try:
            tombstone_orphaned_ch_persons(
                context.team_id,
                list(chunk),
                dry_run=False,
                on_outcome=partial(_collect_outcome, outcomes),
            )
        except Exception:
            for person_uuid, _ in outcomes:
                context.action(by_uuid[person_uuid], "undelivered")
            raise
        for person_uuid, outcome in outcomes:
            context.action(by_uuid[person_uuid], outcome)


def _strong_row(team_id: int, distinct_id: str) -> DistinctIdRow | None:
    rows = get_distinct_id_rows(team_id, [distinct_id], strong=True)
    return rows[0] if rows else None


def _bury_mapping(row: dict[str, Any], context: VerbContext) -> None:
    team_id, distinct_id = context.team_id, row["key"]
    reported = row["evidence"]["pg"]
    current = _strong_row(team_id, distinct_id)
    if current is None or not current.is_deleted or current.person_id != reported["person_id"]:
        context.action(row, "skipped_changed")
        return
    ch = observe.ch_mapping_states(team_id, [distinct_id]).get(distinct_id)
    if ch is None or ch.visible_rows == 0 or ch.winner_deleted:
        context.action(row, "skipped_not_divergent")
        return
    target = max(int(current.version), ch.max_version + 1)
    if not context.apply:
        context.action(row, "would_repair", target_version=target)
        return
    if current.version < target:
        context.pacer.before_write()
        repairs._raise_mapping_version_floor(team_id, distinct_id, target)
    confirmed = _strong_row(team_id, distinct_id)
    if confirmed is None or not confirmed.is_deleted or confirmed.person_id != current.person_id:
        # An attach revived the row between the reads; ingestion publishes the live row above the raise.
        context.action(row, "skipped_revived")
        return
    owner = confirmed.person_uuid if confirmed.HasField("person_uuid") else ch.winner_person_uuid
    context.deliveries.track(
        create_person_distinct_id(team_id, distinct_id, owner, version=int(confirmed.version), is_deleted=True),
        repairs.PublishedKey(kind="mapping", key=distinct_id),
    )
    context.action(row, "buried", version=int(confirmed.version))


VERBS: dict[str, VerbFn] = {
    "republish": republish,
    "merge_stale": merge_stale,
    "bury": bury,
    "restore": restore_verbs.restore,
    "fold": restore_verbs.fold,
    "merge": restore_verbs.merge,
}
