"""Canvas visibility reads for other products.

Separate from ``facade/api.py`` because request paths such as the activity log and comments
call these reads, and ``api.py`` pulls the build path (and Temporal) onto import.
"""

from collections.abc import Iterable
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet

from posthog.models.user import User

from products.canvas.backend.facade.contracts import CanvasSummary
from products.canvas.backend.models import Canvas
from products.tasks.backend.facade import api as tasks_facade


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
    return (
        _visible_canvases(team_id, user_id).filter(id=canvas_id, source_policy=Canvas.SOURCE_POLICY_STANDARD).exists()
    )


def channel_has_canvases(*, team_id: int, channel_id: UUID) -> bool:
    return Canvas.objects.for_team(team_id).filter(channel_id=channel_id, deleted=False).exists()


def live_canvas_summary(*, team_id: int, canvas_id: str) -> CanvasSummary | None:
    """The live canvas with this id, without a visibility check."""
    try:
        canvas = (
            Canvas.objects.for_team(team_id)
            .filter(id=canvas_id, deleted=False)
            .select_related("channel")
            .only("id", "name", "channel_id", "channel__name")
            .first()
        )
    except (ValueError, ValidationError):
        return None
    return _summary(canvas) if canvas is not None else None


def visible_canvas_summaries(
    *, team_id: int, user_id: int | None, canvas_ids: Iterable[UUID]
) -> dict[str, CanvasSummary]:
    """The live canvases from `canvas_ids` that the user may see, keyed by canvas id string."""
    ids = list(canvas_ids)
    if not ids:
        return {}
    canvases = (
        _visible_canvases(team_id, user_id)
        .filter(id__in=ids)
        .select_related("channel")
        .only("id", "name", "channel_id", "channel__name")
    )
    return {str(canvas.id): _summary(canvas) for canvas in canvases}


def live_visible_canvas_ids(team_id: int, user_id: int | None, canvas_ids: Iterable[str]) -> set[str]:
    """The ids from `canvas_ids` of live canvases that the user may see, in any source policy.

    Ids that are not UUIDs are dropped, so callers can pass free-form comment item ids.
    """
    candidates = []
    for canvas_id in canvas_ids:
        try:
            candidates.append(UUID(canvas_id))
        except (TypeError, ValueError):
            continue
    if not candidates:
        return set()
    visible = _visible_canvases(team_id, user_id).filter(id__in=candidates).values_list("id", flat=True)
    return {str(canvas_id) for canvas_id in visible}


def visible_canvas_ids(team_id: int, user: User | None) -> set[str]:
    """Ids of this team's canvases that the ordinary Canvas API exposes to the user.

    Used to restrict `Canvas`-scoped rows in the team activity feed; a canvas hidden
    from `CanvasViewSet` must not leak its history here either. Includes the user's own
    soft-deleted canvases so an owner still sees their deleted canvas's history.
    """
    user_id = getattr(user, "id", None)
    canvases = Canvas.objects.for_team(team_id).filter(
        tasks_facade.visible_channels_q(user_id, relation="channel"),
        _live_or_owned_q(user_id),
        source_policy=Canvas.SOURCE_POLICY_STANDARD,
    )
    return {str(canvas_id) for canvas_id in canvases.values_list("id", flat=True)}


def visible_canvas_user_ids(*, team_id: int, canvas_id: str, user_ids: Iterable[int]) -> set[int]:
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
    """Ids of canvases hidden by channel visibility, source policy, or deletion across an org.

    Cross-team by design, hence `unscoped()`.
    """
    user_id = getattr(user, "id", None)
    hidden = (
        Canvas.objects.unscoped()
        .filter(team__organization_id=organization_id)
        .filter(
            ~tasks_facade.visible_channels_q(user_id, relation="channel")
            | ~Q(source_policy=Canvas.SOURCE_POLICY_STANDARD)
            | ~_live_or_owned_q(user_id)
        )
    )
    return {str(canvas_id) for canvas_id in hidden.values_list("id", flat=True)}


def _live_or_owned_q(user_id: int | None) -> Q:
    """A soft-deleted canvas stays in the activity feeds of its owner only."""
    return Q(deleted=False) | Q(created_by_id=user_id) if user_id is not None else Q(deleted=False)


def _visible_canvases(team_id: int, user_id: int | None) -> QuerySet[Canvas]:
    return Canvas.objects.for_team(team_id).filter(
        tasks_facade.visible_channels_q(user_id, relation="channel"), deleted=False
    )


def _summary(canvas: Canvas) -> CanvasSummary:
    return CanvasSummary(id=canvas.id, name=canvas.name, channel_id=canvas.channel_id, channel_name=canvas.channel.name)
