"""Facade API for the annotations product — the surface other products may import.

Thin by design: accept ids, return ids, never ORM instances.
"""

from datetime import datetime

from django.utils import timezone

from posthog.models import Team

from products.annotations.backend.models.annotation import Annotation

__all__ = ["create_project_annotation"]


def create_project_annotation(
    team_id: int, user_id: int | None, *, content: str, date_marker: datetime | None = None
) -> int:
    """Create a project-scoped annotation as the user, returning its id.

    ``date_marker`` defaults to the creation time when omitted — a null marker
    would keep the annotation off every chart and out of AI context, which is
    never what a project annotation wants.
    """
    team = Team.objects.get(id=team_id)
    annotation = Annotation.objects.create(
        team_id=team_id,
        organization_id=team.organization_id,
        created_by_id=user_id,
        content=content,
        date_marker=date_marker if date_marker is not None else timezone.now(),
        scope=Annotation.Scope.PROJECT,
    )
    return annotation.id
