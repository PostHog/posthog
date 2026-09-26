"""Canvas facade API for cross-product access.

Separate from ``facade/search.py`` because the tasks app imports search.py at ``django.setup()``
to wire its index, and this module pulls the build path (and Temporal) onto startup.
"""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet
from django.http import HttpRequest

from posthog.models.user import User

from products.canvas.backend.artifacts import canvas_artifact as _canvas_artifact
from products.canvas.backend.connectors import (
    call_connector_tool as call_connector_tool,
    canvas_connectors_enabled as canvas_connectors_enabled,
    connector_listings as connector_listings,
    mcp_provider_host as mcp_provider_host,
    native_connector_listings as native_connector_listings,
)
from products.canvas.backend.facade.contracts import CanvasArtifact
from products.canvas.backend.facade.enums import (
    ConnectorCallStatus as ConnectorCallStatus,
    ConnectorKind as ConnectorKind,
)
from products.canvas.backend.layout import (
    CANVAS_LAYOUT_SCHEMA_VERSION as CANVAS_LAYOUT_SCHEMA_VERSION,
    MAX_LAYOUT_PATCH_OPERATIONS as MAX_LAYOUT_PATCH_OPERATIONS,
    PLACEMENT_ID_RE as PLACEMENT_ID_RE,
    PLACEMENT_STATUSES as PLACEMENT_STATUSES,
    apply_layout_ops as apply_layout_ops,
    default_layout as default_layout,
    subtract_preexisting_diagnostics as subtract_preexisting_diagnostics,
    validate_layout as validate_layout,
    validate_layout_references as validate_layout_references,
)
from products.canvas.backend.models import Canvas
from products.canvas.backend.state_reads import CanvasStateReader as CanvasStateReader
from products.canvas.backend.teaching import (
    RESERVED_TEMPLATE_IDS as RESERVED_TEMPLATE_IDS,
    TEACHING_CANVAS_NAME as TEACHING_CANVAS_NAME,
    seed_teaching_canvas as seed_teaching_canvas,
)
from products.canvas.backend.welcome import seed_home_canvas as seed_home_canvas
from products.tasks.backend.facade import api as tasks_facade


def render_canvas_artifact(*, host: str, token: str, artifact_path: str, if_none_match: str | None) -> CanvasArtifact:
    request = HttpRequest()
    request.META["HTTP_HOST"] = host
    if if_none_match is not None:
        request.META["HTTP_IF_NONE_MATCH"] = if_none_match
    response = _canvas_artifact(request, token, artifact_path)
    return CanvasArtifact(
        status_code=response.status_code,
        body=response.content,
        headers=dict(response.items()),
    )


def canvas_belongs_to_task(*, team_id: int, user_id: int | None, canvas_id: str, task_id: UUID) -> bool:
    try:
        return (
            _visible_canvases(team_id, user_id)
            .filter(id=canvas_id)
            .filter(Q(generation_task_id=task_id) | Q(source_versions__task_id=task_id))
            .exists()
        )
    except (ValueError, ValidationError):
        return False


def canvas_owner_id(*, team_id: int, canvas_id: str) -> int | None:
    try:
        return (
            Canvas.objects.for_team(team_id)
            .filter(id=canvas_id, deleted=False)
            .values_list("created_by_id", flat=True)
            .first()
        )
    except (ValueError, ValidationError):
        return None


def canvas_is_visible(*, team_id: int, canvas_id: str | UUID, user_id: int | None) -> bool:
    """Whether `canvas_id` is a live canvas in this team that the user may see."""
    return _visible_canvases(team_id, user_id).filter(id=canvas_id).exists()


def channel_has_canvases(*, team_id: int, channel_id: UUID) -> bool:
    return Canvas.objects.for_team(team_id).filter(channel_id=channel_id, deleted=False).exists()


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


def visible_canvas_user_ids(*, team_id: int, canvas_id: str, user_ids: set[int] | list[int]) -> set[int]:
    """User IDs from the given list that can access the specified canvas.

    Filters by channel visibility: public channels grant access to all, personal channels
    to their creator, and private channels to their members.
    """
    candidate_ids = set(user_ids) if not isinstance(user_ids, set) else user_ids
    if not candidate_ids:
        return set()
    try:
        canvases = Canvas.objects.for_team(team_id).filter(id=canvas_id, deleted=False, channel__deleted=False)
        if canvases.filter(channel__channel_type="public").exists():
            return candidate_ids
        visible_ids = set(
            canvases.filter(channel__channel_type="personal", channel__created_by_id__in=candidate_ids).values_list(
                "channel__created_by_id", flat=True
            )
        )
        visible_ids.update(
            canvases.filter(
                channel__channel_type="private", channel__memberships__user_id__in=candidate_ids
            ).values_list("channel__memberships__user_id", flat=True)
        )
        return visible_ids
    except (ValueError, ValidationError):
        return set()


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


def _visible_canvases(team_id: int, user_id: int | None) -> QuerySet[Canvas]:
    return Canvas.objects.for_team(team_id).filter(
        tasks_facade.visible_channels_q(user_id, relation="channel"), deleted=False
    )
