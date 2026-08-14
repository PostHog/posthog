"""Facade API for the annotations product — the surface other products may import.

Thin by design: accept ids, return ids, never ORM instances.
"""

from datetime import datetime

from posthog.models import Team

from products.annotations.backend.models.annotation import Annotation

__all__ = ["create_project_annotation"]


def create_project_annotation(
    team_id: int, user_id: int | None, *, content: str, date_marker: datetime | None = None
) -> int:
    """Create a project-scoped annotation as the user, returning its id."""
    team = Team.objects.get(id=team_id)
    annotation = Annotation.objects.create(
        team_id=team_id,
        organization_id=team.organization_id,
        created_by_id=user_id,
        content=content,
        date_marker=date_marker,
        scope=Annotation.Scope.PROJECT,
    )
    return annotation.id
