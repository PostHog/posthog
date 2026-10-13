"""Canvas visibility reads for other products.

Separate from ``facade/api.py`` because request paths such as the activity log and comments
call these reads, and ``api.py`` pulls the build path (and Temporal) onto import.
"""

from collections.abc import Iterable
from uuid import UUID

from products.canvas.backend.facade.contracts import CanvasOwnerActivity, CanvasSummary
from products.canvas.backend.logic import visibility


def canvas_comments_accessible(
    *, team_id: int, user_id: int | None, canvas_id: str, task_id: UUID | None = None, sandbox: bool = False
) -> bool:
    """Whether the user may comment on this live canvas, and when `task_id` is set, whether the task built it."""
    return visibility.canvas_comments_accessible(
        team_id=team_id, user_id=user_id, canvas_id=canvas_id, task_id=task_id, sandbox=sandbox
    )


def canvas_owner_id(*, team_id: int, canvas_id: str) -> int | None:
    return visibility.canvas_owner_id(team_id=team_id, canvas_id=canvas_id)


def canvas_is_visible(*, team_id: int, canvas_id: str | UUID, user_id: int | None) -> bool:
    """Whether `canvas_id` is a live canvas in this team that the user may see."""
    return visibility.canvas_is_visible(team_id=team_id, canvas_id=canvas_id, user_id=user_id)


def channel_has_canvases(*, team_id: int, channel_id: UUID) -> bool:
    return visibility.channel_has_canvases(team_id=team_id, channel_id=channel_id)


def live_canvas_summary(*, team_id: int, canvas_id: str) -> CanvasSummary | None:
    """The live canvas with this id, without a visibility check."""
    return visibility.live_canvas_summary(team_id=team_id, canvas_id=canvas_id)


def visible_canvas_summaries(
    *, team_id: int, user_id: int | None, canvas_ids: Iterable[UUID]
) -> dict[str, CanvasSummary]:
    """The live canvases from `canvas_ids` that the user may see, keyed by canvas id string."""
    return visibility.visible_canvas_summaries(team_id=team_id, user_id=user_id, canvas_ids=canvas_ids)


def live_visible_canvas_ids(team_id: int, user_id: int | None, canvas_ids: Iterable[str]) -> set[str]:
    """The ids from `canvas_ids` of live canvases that the user may see, in any source policy.

    Ids that are not UUIDs are dropped, so callers can pass free-form comment item ids.
    """
    return visibility.live_visible_canvas_ids(team_id, user_id, canvas_ids)


def visible_canvas_ids(team_id: int, user_id: int | None) -> set[str]:
    """Ids of this team's canvases that the ordinary Canvas API exposes to the user.

    Used to restrict `Canvas`-scoped rows in the team activity feed; a canvas hidden
    from `CanvasViewSet` must not leak its history here either. Includes the user's own
    soft-deleted canvases so an owner still sees their deleted canvas's history.
    """
    return visibility.visible_canvas_ids(team_id, user_id)


def visible_canvas_user_ids(*, team_id: int, canvas_id: str, user_ids: Iterable[int]) -> set[int]:
    """User IDs from the given list that can access the specified canvas.

    Filters by channel visibility: public channels grant access to all, personal channels
    to their creator, and private channels to their members.
    """
    return visibility.visible_canvas_user_ids(team_id=team_id, canvas_id=canvas_id, user_ids=user_ids)


def canvas_owner_activity(*, team_id: int, channel_ids: Iterable[UUID]) -> list[CanvasOwnerActivity]:
    """The last change each owner made to their live canvases, per channel among `channel_ids`."""
    return visibility.canvas_owner_activity(team_id=team_id, channel_ids=channel_ids)


def hidden_canvas_ids_for_org(organization_id: str | UUID, user_id: int | None) -> set[str]:
    """Ids of canvases hidden by channel visibility, source policy, or deletion across an org."""
    return visibility.hidden_canvas_ids_for_org(organization_id, user_id)
