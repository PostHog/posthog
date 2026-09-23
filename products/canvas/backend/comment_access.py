from collections.abc import Iterable
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q

from products.canvas.backend.models import Canvas
from products.tasks.backend.facade import api as tasks_facade


def canvas_belongs_to_task(*, team_id: int, user_id: int | None, canvas_id: str, task_id: UUID) -> bool:
    try:
        return (
            Canvas.objects.for_team(team_id)
            .filter(id=canvas_id, deleted=False)
            .filter(tasks_facade.visible_channels_q(user_id, relation="channel"))
            .filter(Q(generation_task_id=task_id) | Q(source_versions__task_id=task_id))
            .exists()
        )
    except (ValueError, ValidationError):
        return False


def visible_canvas_user_ids(*, team_id: int, canvas_id: str, user_ids: Iterable[int]) -> set[int]:
    candidate_ids = set(user_ids)
    if not candidate_ids:
        return set()
    try:
        canvases = Canvas.objects.for_team(team_id).filter(id=canvas_id, deleted=False, channel__deleted=False)
        if canvases.filter(channel__channel_type="public").exists():
            return candidate_ids
        visible_ids = set(
            canvases.filter(channel__channel_type="personal", channel__created_by_id__in=candidate_ids).values_list(
                "channel__created_by_id", flat=True
            )
        )
        visible_ids.update(
            canvases.filter(
                channel__channel_type="private", channel__memberships__user_id__in=candidate_ids
            ).values_list("channel__memberships__user_id", flat=True)
        )
        return visible_ids
    except (ValueError, ValidationError):
        return set()


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
