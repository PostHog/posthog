from uuid import UUID

from django.utils import timezone

from products.canvas.backend.models import Canvas, CanvasSourceVersion


def create_report_canvas(*, team_id: int, channel_id: str | UUID, name: str, discussion_task_id: str | UUID) -> UUID:
    canvas = Canvas.objects.for_team(team_id).create(
        team_id=team_id,
        channel_id=channel_id,
        name=name,
        discussion_task_id=discussion_task_id,
    )
    return canvas.id


def set_generation_task(*, team_id: int, canvas_id: str | UUID, task_id: str | UUID) -> None:
    updated = Canvas.objects.for_team(team_id).filter(id=canvas_id).update(generation_task_id=task_id)
    if updated != 1:
        raise Canvas.DoesNotExist(canvas_id)


def get_canvas_channel_id(*, team_id: int, canvas_id: str | UUID) -> UUID:
    return Canvas.objects.for_team(team_id).values_list("channel_id", flat=True).get(id=canvas_id)


def set_canvas_name(*, team_id: int, canvas_id: str | UUID, name: str) -> None:
    updated = Canvas.objects.for_team(team_id).filter(id=canvas_id).update(name=name, updated_at=timezone.now())
    if updated != 1:
        raise Canvas.DoesNotExist(canvas_id)


def canvas_generation_result(*, team_id: int, canvas_id: str | UUID, task_id: str | UUID) -> tuple[bool, bool]:
    canvas = Canvas.objects.for_team(team_id).get(id=canvas_id)
    published = canvas.source_versions.filter(task_id=task_id, draft=False).exists()
    drafted = CanvasSourceVersion.objects.for_team(team_id).filter(canvas=canvas, task_id=task_id, draft=True).exists()
    return published, drafted
