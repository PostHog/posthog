"""Which canvases a caller may reach through the canvas API."""

from django.db.models import Q, QuerySet

from products.access_control.backend.facade import api as access_control_facade
from products.canvas.backend.facade.contracts import CanvasViewer
from products.canvas.backend.facade.enums import CanvasAccess
from products.canvas.backend.models import Canvas
from products.tasks.backend.facade import api as tasks_facade

# The access modes a sandbox may use on public canvases, not only on its actor's own.
_SANDBOX_VISIBLE_ACCESS = {CanvasAccess.READ, CanvasAccess.STATE, CanvasAccess.EDIT}


def authorized_canvases(viewer: CanvasViewer, access: CanvasAccess) -> QuerySet[Canvas]:
    """Standard-policy canvases of the viewer's team that `access` may reach, newest first.

    A notebook-widget canvas is never reachable here: notebooks own those canvases.
    """
    # unscoped() plus an explicit team filter, because the viewer's team id is already canonical.
    queryset = Canvas.objects.unscoped().filter(
        team_id=viewer.team_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_STANDARD
    )
    if viewer.sandboxed:
        if viewer.sandbox_task_id is None:
            return queryset.none()
        public_canvas_q = tasks_facade.visible_channels_q(None, relation="channel")
        if viewer.user_id is None:
            return (queryset.filter(public_canvas_q) if access == CanvasAccess.READ else queryset.none()).order_by(
                "-created_at", "-id"
            )
        actor_canvas_q = Q(created_by_id=viewer.user_id) & tasks_facade.visible_channels_q(
            viewer.user_id, relation="channel"
        )
        return queryset.filter(
            public_canvas_q | actor_canvas_q if access in _SANDBOX_VISIBLE_ACCESS else actor_canvas_q
        ).order_by("-created_at", "-id")

    # Channels are per-user for the personal kind: the facade's visibility
    # rule makes a canvas filed into someone else's personal channel
    # invisible (and unwritable) to everyone but its owner.
    queryset = queryset.filter(tasks_facade.visible_channels_q(viewer.user_id, relation="channel"))
    if access == CanvasAccess.EDIT:
        if viewer.user_id is None:
            return queryset.none()
        # An editor grant on the canvas itself lets a member of a private space edit it too. It
        # only applies within the space visibility above, so a personal space stays its owner's.
        granted_ids = access_control_facade.object_ids_granted_to_user(
            team_id=viewer.team_id, resource="canvas", user_id=viewer.user_id, required_level="editor"
        )
        queryset = queryset.filter(
            Q(created_by_id=viewer.user_id)
            | tasks_facade.visible_channels_q(None, relation="channel")
            | Q(id__in=granted_ids)
        )
    elif access == CanvasAccess.DELETE:
        if viewer.user_id is None:
            return queryset.none()
        queryset = queryset.filter(created_by_id=viewer.user_id)
    return queryset.order_by("-created_at", "-id")
