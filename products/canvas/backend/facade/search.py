"""Read hooks for the tasks search index.

Separate from ``facade/api.py`` because the tasks app imports this at ``django.setup()``
to wire its index, and ``api.py`` pulls the build path (and Temporal) onto startup.
"""

from collections.abc import Iterator
from uuid import UUID

from products.canvas.backend.facade.contracts import CanvasSearchRecord
from products.canvas.backend.models import Canvas


def searchable_canvas(*, team_id: int, canvas_id: UUID) -> CanvasSearchRecord | None:
    """The canvas as the tasks search index sees it, or None when search must not show it."""
    canvas = Canvas.objects.for_team(team_id).filter(id=canvas_id).first()
    if canvas is None or canvas.deleted or canvas.source_policy != Canvas.SOURCE_POLICY_STANDARD:
        return None
    return CanvasSearchRecord(
        id=canvas.id,
        team_id=canvas.team_id,
        name=canvas.name,
        channel_id=canvas.channel_id,
        kind=canvas.kind,
        template_id=canvas.template_id,
    )


def list_canvas_ids(team_id: int) -> Iterator[UUID]:
    """Every canvas id of the team and its environments, deleted ones included."""
    return Canvas.objects.for_team(team_id, canonical=True).values_list("id", flat=True).iterator()
