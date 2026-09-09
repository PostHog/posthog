from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, cast
from uuid import UUID

from django.db import transaction

from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.canvas.backend.facade.enums import SketchpadRecordKind
from products.canvas.backend.models import Sketchpad, SketchpadCompileJob, SketchpadOp, SketchpadRecord
from products.canvas.backend.sketchpad.records import (
    JsonObject,
    JsonValue,
    SketchpadRecords,
    hydrate_ops,
    merge_field,
    op_source_refs,
    source_refs,
)

SKETCHPAD_HISTORY_LIMIT = 10_000
SKETCHPAD_COMPACTION_CHUNK = 1_000


class SketchpadHistoryCompacted(APIException):
    status_code = 409
    default_detail = "This edit is older than the retained sketchpad history. Reload the sketchpad before retrying it."
    default_code = "history_compacted"


@frozen
class SketchpadAppendResult:
    results: list[SketchpadOp]
    replayed: list[SketchpadOp]
    head_seq: int
    appended: list[SketchpadOp]


def append_ops(
    sketchpad: Sketchpad,
    ops: Sequence[Mapping[str, Any]],
    actor_kind: str,
    actor_task_id: UUID | None,
    user: User | None,
    base_seq: int = 0,
) -> SketchpadAppendResult:
    appended: list[SketchpadOp] = []
    replayed: dict[str, SketchpadOp] = {}
    with transaction.atomic():
        locked = Sketchpad.objects.for_team(sketchpad.team_id).select_for_update().get(pk=sketchpad.pk)
        scoped_ops = SketchpadOp.objects.for_team(sketchpad.team_id)
        existing = {
            row.op_id: row
            for row in scoped_ops.filter(sketchpad=locked, op_id__in=[entry["op_id"] for entry in ops]).select_related(
                "actor_user"
            )
        }
        if base_seq < locked.history_start_seq and any(entry["op_id"] not in existing for entry in ops):
            raise SketchpadHistoryCompacted()
        records = SketchpadRecords(locked)
        if any(entry["op_id"] not in existing for entry in ops):
            records.prepare([entry["op"] for entry in ops])
        results: list[SketchpadOp] = []
        for entry in ops:
            op_id = entry["op_id"]
            if op_id in existing:
                results.append(existing[op_id])
                replayed[op_id] = existing[op_id]
                continue
            row = SketchpadOp(
                team_id=locked.team_id,
                sketchpad=locked,
                seq=locked.head_seq + 1,
                op_id=op_id,
                actor_kind=actor_kind,
                actor_user=user,
                actor_task_id=actor_task_id,
                op=records.apply(entry["op"], locked.head_seq + 1),
            )
            existing[op_id] = row
            locked.head_seq = row.seq
            appended.append(row)
            results.append(row)
        scoped_ops.bulk_create(appended)
        if appended:
            records.validate_limits()
            records.save()
            hydrate_ops(appended)
            _compact_history(locked)
            locked.save(update_fields=["head_seq", "updated_at"])
    sketchpad.head_seq = locked.head_seq
    return SketchpadAppendResult(
        results=results, replayed=list(replayed.values()), head_seq=locked.head_seq, appended=appended
    )


def _compact_history(sketchpad: Sketchpad) -> None:
    excess = sketchpad.head_seq - sketchpad.history_start_seq - SKETCHPAD_HISTORY_LIMIT
    if excess <= 0:
        return
    target_seq = sketchpad.history_start_seq + max(excess, SKETCHPAD_COMPACTION_CHUNK)
    ops = list(
        SketchpadOp.objects.for_team(sketchpad.team_id)
        .filter(sketchpad=sketchpad, seq__gt=sketchpad.history_start_seq, seq__lte=target_seq)
        .order_by("seq")
    )
    hydrate_ops(ops)
    sketchpad.history_snapshot = fold_snapshot(cast(JsonObject, sketchpad.history_snapshot), ops)
    sketchpad.history_start_seq = target_seq
    sketchpad.save(update_fields=["history_snapshot", "history_start_seq"])
    SketchpadOp.objects.for_team(sketchpad.team_id).filter(sketchpad=sketchpad, seq__lte=target_seq).delete()
    _remove_unused_sources(sketchpad)


def fold_snapshot(snapshot: JsonObject, rows: Sequence[SketchpadOp]) -> JsonObject:
    current = deepcopy(snapshot)
    for row in rows:
        op = cast(JsonObject, row.op)
        op_type = op["type"]
        if op_type == "restore":
            current = deepcopy(cast(JsonObject, op["snapshot"]))
        elif op_type == "add_fragment":
            fragment = deepcopy(cast(JsonObject, op["fragment"]))
            kept: list[JsonValue] = [
                item for item in cast(list[JsonObject], current.get("fragments", [])) if item["id"] != fragment["id"]
            ]
            kept.append(fragment)
            current["fragments"] = kept
        elif op_type == "update_fragment":
            for fragment in cast(list[JsonObject], current.get("fragments", [])):
                if fragment["id"] == op["id"]:
                    fragment.update(deepcopy(cast(JsonObject, op["patch"])))
                    break
        elif op_type == "remove_fragment":
            current["fragments"] = [
                item for item in cast(list[JsonObject], current.get("fragments", [])) if item["id"] != op["id"]
            ]
        elif op_type == "bring_to_front":
            fragments = cast(list[JsonObject], current.get("fragments", []))
            top = max((cast(int, item.get("z", 0)) for item in fragments), default=0) + 1
            for fragment in fragments:
                if fragment["id"] == op["id"]:
                    fragment["z"] = top
                    break
        elif op_type == "set_state":
            state = cast(JsonObject, current.setdefault("state", {}))
            if op["value"] is None:
                state.pop(cast(str, op["key"]), None)
            else:
                state[cast(str, op["key"])] = deepcopy(op["value"])
        elif op_type == "edit_field":
            state = cast(JsonObject, current.setdefault("state", {}))
            key = cast(str, op["key"])
            state[key] = merge_field(state.get(key), op)
    return current


def _remove_unused_sources(sketchpad: Sketchpad) -> None:
    records = SketchpadRecord.objects.for_team(sketchpad.team_id).filter(sketchpad=sketchpad)
    fragments = cast(
        list[JsonObject], records.filter(kind=SketchpadRecordKind.FRAGMENT).values_list("value", flat=True)
    )
    retained_ops = SketchpadOp.objects.for_team(sketchpad.team_id).filter(sketchpad=sketchpad).only("op")
    compile_refs = (
        SketchpadCompileJob.objects.for_team(sketchpad.team_id)
        .filter(sketchpad=sketchpad)
        .values_list("refs", flat=True)
    )
    used = source_refs(fragments) | op_source_refs(retained_ops)
    for refs in compile_refs:
        used.update(ref for ref in refs if isinstance(ref, str))
    records.filter(kind=SketchpadRecordKind.SOURCE).exclude(key__in=used).delete()
