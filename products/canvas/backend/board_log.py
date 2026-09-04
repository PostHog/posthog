import json
from collections.abc import Mapping, Sequence
from typing import Any

from django.db import transaction

from posthog.models.user import User

from products.canvas.backend import board_stream
from products.canvas.backend.models import CanvasBoard, CanvasBoardOp

BOARD_OP_TYPES = [
    "add_fragment",
    "update_fragment",
    "remove_fragment",
    "bring_to_front",
    "set_state",
    "restore",
    "edit_field",
]
MAX_BOARD_OP_BYTES = 256 * 1024


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


class InvalidBoardOpError(ValueError):
    """An op the server refuses to record."""


def validate_op(op: Any) -> None:
    if not isinstance(op, dict):
        raise InvalidBoardOpError("Each op must be a JSON object.")
    op_type = op.get("type")
    if not isinstance(op_type, str) or op_type not in BOARD_OP_TYPES:
        raise InvalidBoardOpError(f"op.type must be one of: {', '.join(BOARD_OP_TYPES)}.")
    if len(json.dumps(op, separators=(",", ":")).encode()) > MAX_BOARD_OP_BYTES:
        raise InvalidBoardOpError(f"Each op is capped at {MAX_BOARD_OP_BYTES // 1024} KB serialized.")


def append_ops(
    board: CanvasBoard,
    ops: Sequence[Mapping[str, Any]],
    actor_kind: str,
    actor_task_id: str | None,
    user: User | None,
    base_seq: int,
    snapshot: dict[str, Any] | None,
) -> list[CanvasBoardOp]:
    """Record ``ops`` on the board's log and return one row per incoming op, in order.

    A row whose ``op_id`` the board already holds is returned as-is instead of
    being appended again. ``snapshot`` is stored only when ``base_seq`` matches
    the head before this call, so a stale client cannot overwrite a newer fold.

    Newly recorded ops go to the board's live stream once the transaction
    commits, so an op never reaches a collaborator before it is durable.
    """
    for entry in ops:
        validate_op(entry["op"])
    appended: list[CanvasBoardOp] = []
    with transaction.atomic():
        locked = CanvasBoard.objects.for_team(board.team_id).select_for_update().get(pk=board.pk)
        head_before = locked.head_seq
        scoped_ops = CanvasBoardOp.objects.for_team(board.team_id)
        existing = {
            row.op_id: row for row in scoped_ops.filter(board=locked, op_id__in=[entry["op_id"] for entry in ops])
        }
        results: list[CanvasBoardOp] = []
        for entry in ops:
            op_id = entry["op_id"]
            if op_id in existing:
                results.append(existing[op_id])
                continue
            row = scoped_ops.create(
                team_id=locked.team_id,
                board=locked,
                seq=locked.head_seq + 1,
                op_id=op_id,
                actor_kind=actor_kind,
                actor_user=user,
                actor_task_id=actor_task_id,
                op=entry["op"],
            )
            existing[op_id] = row
            locked.head_seq = row.seq
            appended.append(row)
            results.append(row)
        update_fields = ["head_seq", "updated_at"]
        if snapshot is not None and base_seq == head_before:
            locked.snapshot = snapshot
            locked.snapshot_seq = locked.head_seq
            update_fields += ["snapshot", "snapshot_seq"]
        locked.save(update_fields=update_fields)
        if appended:
            team_id = locked.team_id
            board_key = str(locked.pk)
            events = [_op_event(row, user) for row in appended]
            transaction.on_commit(lambda: board_stream.publish_ops(team_id, board_key, events))
    board.head_seq = locked.head_seq
    board.snapshot = locked.snapshot
    board.snapshot_seq = locked.snapshot_seq
    board.updated_at = locked.updated_at
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
