"""Canvas activity-log visibility, mirroring products.tasks loops.

Canvas activity rows are team-scoped in the log, but a canvas filed in a personal
channel is owner-only (`CanvasViewSet` filters every action through
`Channel.visible_to_q`). Without these filters a teammate with activity-log access
could read another member's personal-canvas names, ids, and declared capabilities
out of the team- or org-wide feed. Canvases are soft-deleted (the row persists), so
visibility stays computable from the `Canvas` table without snapshotting context.
"""

from uuid import UUID

from posthog.models.user import User

from products.canvas.backend.models import Canvas
from products.tasks.backend.models import Channel


def visible_canvas_ids(team_id: int, user: User | None) -> set[str]:
    """Ids (as strings) of this team's canvases whose channel the user may see.

    Used to restrict `Canvas`-scoped rows in the team activity feed; a canvas hidden
    from `CanvasViewSet` must not leak its history here either. Includes soft-deleted
    canvases so an owner still sees their deleted canvas's history.
    """
    user_id = getattr(user, "id", None)
    canvases = Canvas.objects.for_team(team_id).filter(Channel.visible_to_q(user_id, relation="channel"))
    return {str(canvas_id) for canvas_id in canvases.values_list("id", flat=True)}


def hidden_personal_canvas_ids_for_org(organization_id: str | UUID, user: User | None) -> set[str]:
    """Ids (as strings) of personal-channel canvases across an org NOT owned by `user`.

    The org-wide feed (org admins/owners) must still keep other people's personal
    canvases out. Cross-team by design, hence `unscoped()`.
    """
    user_id = getattr(user, "id", None)
    hidden = Canvas.objects.unscoped().filter(
        team__organization_id=organization_id, channel__channel_type=Channel.ChannelType.PERSONAL
    )
    if user_id is not None:
        hidden = hidden.exclude(channel__created_by_id=user_id)
    return {str(canvas_id) for canvas_id in hidden.values_list("id", flat=True)}
