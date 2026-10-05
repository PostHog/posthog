"""Which canvases a caller may reach through the canvas API."""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet

from products.canvas.backend.facade.contracts import CanvasHiddenBySpaceError, CanvasNotFoundError, CanvasViewer
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
        queryset = queryset.filter(
            Q(created_by_id=viewer.user_id) | tasks_facade.visible_channels_q(None, relation="channel")
        )
    elif access == CanvasAccess.DELETE:
        if viewer.user_id is None:
            return queryset.none()
        queryset = queryset.filter(created_by_id=viewer.user_id)
    return queryset.order_by("-created_at", "-id")


def unreachable_canvas_error(viewer: CanvasViewer, access: CanvasAccess, canvas_id: UUID | str) -> CanvasNotFoundError:
    """The error for a canvas that `authorized_canvases(viewer, access)` did not return.

    A real user who reads a live canvas of their own team, hidden only by its space, gets
    CanvasHiddenBySpaceError, so the client can explain the dead end. Every other miss stays
    an opaque CanvasNotFoundError.
    """
    if access != CanvasAccess.READ or viewer.sandboxed or viewer.user_id is None:
        return CanvasNotFoundError()
    try:
        hidden = (
            Canvas.objects.unscoped()
            .filter(
                team_id=viewer.team_id,
                id=canvas_id,
                deleted=False,
                channel__deleted=False,
                source_policy=Canvas.SOURCE_POLICY_STANDARD,
            )
            .exclude(tasks_facade.visible_channels_q(viewer.user_id, relation="channel"))
            .exists()
        )
    except (ValueError, ValidationError):
        hidden = False
    return CanvasHiddenBySpaceError() if hidden else CanvasNotFoundError()
