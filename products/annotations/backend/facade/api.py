"""Facade API for the annotations product — the surface other products may import.

Thin by design: accept ids, return ids, never ORM instances.
"""

from datetime import datetime
from uuid import UUID

from django.utils import timezone

from posthog.models import Team

from products.annotations.backend import change_feed
from products.annotations.backend.facade.change_feed import ChangeFeed, ChangeKind, ChangeWindow, KindVisibility
from products.annotations.backend.models.annotation import Annotation

__all__ = ["create_project_annotation", "list_changes"]


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


def list_changes(
    *,
    team_id: int,
    organization_id: UUID,
    user_is_staff: bool,
    window: ChangeWindow,
    visibility: dict[ChangeKind, KindVisibility],
    limit: int,
) -> ChangeFeed:
    """Recent production changes the caller may see, newest first. A kind missing from `visibility` is left out."""
    return change_feed.list_changes(
        team_id=team_id,
        organization_id=organization_id,
        user_is_staff=user_is_staff,
        window=window,
        visibility=visibility,
        limit=limit,
    )
