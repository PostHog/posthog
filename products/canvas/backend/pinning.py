from django.db.models import OuterRef, QuerySet, Subquery

from products.canvas.backend.models import Canvas, CanvasPin


def annotate_canvas_pins(queryset: QuerySet[Canvas], *, team_id: int, user_id: int | None) -> QuerySet[Canvas]:
    if user_id is None:
        return queryset
    pins = CanvasPin.objects.for_team(team_id).filter(canvas_id=OuterRef("pk"), user_id=user_id)
    return queryset.annotate(viewer_pinned_at=Subquery(pins.values("pinned_at")[:1]))


def set_canvas_pinned(*, canvas: Canvas, user_id: int, pinned: bool) -> None:
    pins = CanvasPin.objects.for_team(canvas.team_id).filter(canvas_id=canvas.id, user_id=user_id)
    if not pinned:
        pins.delete()
        return
    CanvasPin.objects.for_team(canvas.team_id).get_or_create(
        team_id=canvas.team_id,
        user_id=user_id,
        canvas_id=canvas.id,
    )
