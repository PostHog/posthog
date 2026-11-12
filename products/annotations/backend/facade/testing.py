"""Test-support facade for annotations.

Suites outside this product plant annotation rows through here instead of importing the model.
"""

from datetime import datetime
from uuid import UUID

from products.annotations.backend.facade.enums import AnnotationScope
from products.annotations.backend.models.annotation import Annotation

__all__ = ["create_annotation"]


def create_annotation(
    *,
    team_id: int,
    organization_id: UUID | None = None,
    content: str | None = None,
    scope: AnnotationScope = AnnotationScope.INSIGHT,
    date_marker: datetime | None = None,
    deleted: bool = False,
    created_by_id: int | None = None,
    insight_id: int | None = None,
    dashboard_id: int | None = None,
) -> int:
    """Store an annotation as given, with no rule checks, and return its id.

    The defaults are the model defaults, so a row planted with only a team is the row a bare create stores.
    """
    return Annotation.objects.create(
        team_id=team_id,
        organization_id=organization_id,
        content=content,
        scope=scope.value,
        date_marker=date_marker,
        deleted=deleted,
        created_by_id=created_by_id,
        dashboard_item_id=insight_id,
        dashboard_id=dashboard_id,
    ).id
