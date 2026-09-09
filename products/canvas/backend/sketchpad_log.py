from collections.abc import Mapping, Sequence
from typing import Any

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.canvas.backend.models import Sketchpad, SketchpadOp
from products.canvas.backend.sketchpad_records import SketchpadRecords, hydrate_ops


@frozen
class SketchpadAppendResult:
    results: list[SketchpadOp]
    replayed: list[SketchpadOp]
    head_seq: int


def sketchpad_actor_name(user: User | None) -> str | None:
    if user is None:
        return None
    return user.first_name or user.email


def sketchpad_actor_person(user: User | None, user_id: int | None = None) -> dict[str, Any]:
    if user is None:
        return {"user_id": user_id, "user_uuid": None, "user_name": None, "user_email": None}
    return {
        "user_id": user.pk,
        "user_uuid": str(user.uuid),
        "user_name": sketchpad_actor_name(user),
        "user_email": user.email,
    }


def append_ops(
    sketchpad: Sketchpad,
    ops: Sequence[Mapping[str, Any]],
    actor_kind: str,
    actor_task_id: str | None,
    user: User | None,
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
            records.save()
            locked.save(update_fields=["head_seq", "updated_at"])
            hydrate_ops(appended)
    sketchpad.head_seq = locked.head_seq
    return SketchpadAppendResult(results=results, replayed=list(replayed.values()), head_seq=locked.head_seq)
