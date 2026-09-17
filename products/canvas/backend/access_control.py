"""Object-level access control for canvases, applied outside the canvas viewset.

`CanvasViewSet` layers per-object access control on top of the channel rule, so every
other surface that reads canvases has to apply the same rule: a canvas denied on the
API must not leak its history, its discussion, or its contract through a side door.
"""

from django.db.models import QuerySet

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.canvas.backend.models import Canvas


def filter_canvases_by_access_level(canvases: QuerySet[Canvas], team_id: int, user: User | None) -> QuerySet[Canvas]:
    """Narrow a canvas queryset to what per-object access control allows the user.

    An anonymous or system caller has no rules to evaluate, so the queryset is returned
    as it came; the caller's own visibility rules still apply.
    """
    if user is None:
        return canvases
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return canvases.none()
    return UserAccessControl(user=user, team=team).filter_queryset_by_access_level(canvases, resource="canvas")


def filter_canvases_by_access_level_for_user_id(
    canvases: QuerySet[Canvas], team_id: int, user_id: int | None
) -> QuerySet[Canvas]:
    """`filter_canvases_by_access_level` for callers that carry a user id rather than a user."""
    user = User.objects.filter(id=user_id).first() if user_id is not None else None
    return filter_canvases_by_access_level(canvases, team_id, user)
