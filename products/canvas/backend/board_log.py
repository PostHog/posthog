from collections.abc import Mapping, Sequence
from typing import Any

from django.db import transaction

from posthog.models.user import User

from products.canvas.backend import board_stream
from products.canvas.backend.board_records import BoardRecords, hydrate_ops
from products.canvas.backend.models import CanvasBoard, CanvasBoardOp


def board_actor_name(user: User | None) -> str | None:
    if user is None:
        return None
    return user.first_name or user.email


def board_actor_person(user: User | None, user_id: int | None = None) -> dict[str, Any]:
    """The identity every board payload carries: enough for an avatar and a name."""
    if user is None:
        return {"user_id": user_id, "user_uuid": None, "user_name": None, "user_email": None}
    return {
        "user_id": user.pk,
        "user_uuid": str(user.uuid),
        "user_name": board_actor_name(user),
        "user_email": user.email,
    }


def append_ops(
    board: CanvasBoard,
    ops: Sequence[Mapping[str, Any]],
    actor_kind: str,
    actor_task_id: str | None,
    user: User | None,
    base_seq: int,
    snapshot: dict[str, Any] | None,
) -> list[CanvasBoardOp]:
    appended: list[CanvasBoardOp] = []
    with transaction.atomic():
        locked = CanvasBoard.objects.for_team(board.team_id).defer("snapshot").select_for_update().get(pk=board.pk)
        scoped_ops = CanvasBoardOp.objects.for_team(board.team_id)
        existing = {
            row.op_id: row for row in scoped_ops.filter(board=locked, op_id__in=[entry["op_id"] for entry in ops])
        }
        records = BoardRecords(locked)
        if any(entry["op_id"] not in existing for entry in ops):
            records.bootstrap()
            records.prepare([entry["op"] for entry in ops])
        results: list[CanvasBoardOp] = []
        for entry in ops:
            op_id = entry["op_id"]
            if op_id in existing:
                results.append(existing[op_id])
                continue
            row = CanvasBoardOp(
                team_id=locked.team_id,
                board=locked,
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
            locked.records_seq = locked.head_seq
            locked.save(update_fields=["head_seq", "records_seq", "updated_at"])
            hydrate_ops(appended)
            team_id = locked.team_id
            board_key = str(locked.pk)
            events = [_op_event(row, user) for row in appended]
            transaction.on_commit(lambda: board_stream.publish_ops(team_id, board_key, events))
    board.head_seq = locked.head_seq
    return results


def _op_event(row: CanvasBoardOp, user: User | None) -> dict[str, Any]:
    """One log entry in the shape ``ops/`` returns, for the board's live stream."""
    return {
        "seq": row.seq,
        "op_id": row.op_id,
        "actor": {
            "kind": row.actor_kind,
            **board_actor_person(user, row.actor_user_id),
            "task_id": row.actor_task_id,
        },
        "created_at": row.created_at.isoformat(),
        "op": row.op,
    }
