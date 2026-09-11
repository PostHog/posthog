"""Test-support facade for canvas.

Suites outside this product plant canvas rows through here instead of importing the
models. The models are team-scoped and fail-closed, so this opens the scope the
insert needs.
"""

from typing import Any
from uuid import UUID

from posthog.models.scoping import team_scope

from products.canvas.backend.models import Canvas, CanvasSourceVersion


def create_canvas(
    *,
    team_id: int,
    channel_id: UUID,
    name: str,
    created_by_id: int | None = None,
    generation_task_id: UUID | None = None,
    source_policy: str = Canvas.SOURCE_POLICY_STANDARD,
    deleted: bool = False,
    canvas_id: UUID | None = None,
) -> UUID:
    fields: dict[str, Any] = {} if canvas_id is None else {"id": canvas_id}
    with team_scope(team_id):
        canvas = Canvas.objects.create(
            team_id=team_id,
            channel_id=channel_id,
            name=name,
            created_by_id=created_by_id,
            generation_task_id=generation_task_id,
            source_policy=source_policy,
            deleted=deleted,
            **fields,
        )
    return canvas.id


def create_canvas_source_version(*, team_id: int, canvas_id: UUID, task_id: UUID, created_by_id: int) -> UUID:
    with team_scope(team_id):
        version = CanvasSourceVersion.objects.create(
            team_id=team_id,
            canvas_id=canvas_id,
            source_hash="a" * 64,
            source_object_key=f"canvases/test/{canvas_id}/source.json",
            source_size=2,
            task_id=task_id,
            created_by_id=created_by_id,
        )
    return version.id


def save_canvas_fields(canvas_id: UUID, *, update_fields: list[str], **values: Any) -> None:
    """Write `values` onto the canvas and save only `update_fields`, so a test can drive
    the save signal the same way production callers do."""
    canvas = Canvas.objects.unscoped().get(id=canvas_id)
    for name, value in values.items():
        setattr(canvas, name, value)
    canvas.save(update_fields=update_fields)
