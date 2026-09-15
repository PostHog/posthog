from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q

from products.canvas.backend.access_control import filter_canvases_by_access_level_for_user_id
from products.canvas.backend.models import Canvas
from products.tasks.backend.facade import api as tasks_facade


def canvas_belongs_to_task(*, team_id: int, user_id: int | None, canvas_id: str, task_id: UUID) -> bool:
    """Whether the user may read and write the discussion attached to this canvas.

    A canvas the API denies must deny its comments too, so the canvas rule is applied
    here as well as the channel rule.
    """
    try:
        canvases = (
            Canvas.objects.for_team(team_id)
            .filter(id=canvas_id, deleted=False)
            .filter(tasks_facade.visible_channels_q(user_id, relation="channel"))
            .filter(Q(generation_task_id=task_id) | Q(source_versions__task_id=task_id))
        )
        return filter_canvases_by_access_level_for_user_id(canvases, team_id, user_id).exists()
    except (ValueError, ValidationError):
        return False


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
