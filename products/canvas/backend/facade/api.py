from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q

from products.canvas.backend.models import Canvas
from products.tasks.backend.facade.api import task_has_canvas_created_event


def canvas_belongs_to_generation_task(*, team_id: int, canvas_id: str, task_id: UUID) -> bool:
    try:
        canvas = Canvas.objects.for_team(team_id).filter(
            id=canvas_id,
            deleted=False,
        )
        if not canvas.exists():
            return False
        relational_owner = canvas.filter(Q(generation_task_id=task_id) | Q(source_versions__task_id=task_id)).exists()
    except (ValueError, ValidationError):
        return False
    return relational_owner or task_has_canvas_created_event(
        team_id=team_id,
        task_id=task_id,
        canvas_id=canvas_id,
    )


def canvas_owner_id(*, team_id: int, canvas_id: str) -> int | None:
    try:
        return (
            Canvas.objects.for_team(team_id)
            .filter(id=canvas_id, deleted=False)
            .values_list("created_by_id", flat=True)
            .first()
        )
    except (ValueError, ValidationError):
        return None
