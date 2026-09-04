"""Canvas activity-log visibility, mirroring Canvas API visibility.

Canvas API visibility requires both an accessible channel and the standard source
policy. The activity feed must apply the same rules or it can expose names, ids, and
declared capabilities for personal or product-managed canvases. Canvases are
soft-deleted, so visibility stays computable without snapshotting context.
"""

from uuid import UUID

from django.db.models import Q

from posthog.models.user import User

from products.canvas.backend.models import Canvas
from products.tasks.backend.facade import api as tasks_facade


def visible_canvas_ids(team_id: int, user: User | None) -> set[str]:
    """Ids of this team's canvases that the ordinary Canvas API exposes to the user.

    Used to restrict `Canvas`-scoped rows in the team activity feed; a canvas hidden
    from `CanvasViewSet` must not leak its history here either. Includes soft-deleted
    canvases so an owner still sees their deleted canvas's history.
    """
    user_id = getattr(user, "id", None)
    canvases = Canvas.objects.for_team(team_id).filter(
        tasks_facade.visible_channels_q(user_id, relation="channel"),
        source_policy=Canvas.SOURCE_POLICY_STANDARD,
    )
    return {str(canvas_id) for canvas_id in canvases.values_list("id", flat=True)}


def hidden_canvas_ids_for_org(organization_id: str | UUID, user: User | None) -> set[str]:
    """Ids of canvases hidden by channel visibility or source policy across an org.

    Cross-team by design, hence `unscoped()`.
    """
    user_id = getattr(user, "id", None)
    hidden = (
        Canvas.objects.unscoped()
        .filter(team__organization_id=organization_id)
        .filter(
            ~tasks_facade.visible_channels_q(user_id, relation="channel")
            | ~Q(source_policy=Canvas.SOURCE_POLICY_STANDARD)
        )
    )
    return {str(canvas_id) for canvas_id in hidden.values_list("id", flat=True)}
