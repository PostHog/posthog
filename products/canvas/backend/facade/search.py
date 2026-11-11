"""Read hooks for the tasks search index.

Separate from ``facade/api.py`` because the tasks app imports this at ``django.setup()``
to wire its index, and ``api.py`` pulls the build path (and Temporal) onto startup.
"""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from uuid import UUID

from products.canvas.backend.facade.contracts import CanvasSearchRecord, CanvasViewer
from products.canvas.backend.models import Canvas

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


def searchable_canvas(*, team_id: int, canvas_id: UUID) -> CanvasSearchRecord | None:
    """The canvas as the tasks search index sees it, or None when search must not show it."""
    canvas = Canvas.objects.for_team(team_id, canonical=True).filter(id=canvas_id).first()
    if canvas is None or canvas.deleted or canvas.source_policy != Canvas.SOURCE_POLICY_STANDARD:
        return None
    return CanvasSearchRecord(
        id=canvas.id,
        team_id=canvas.team_id,
        name=canvas.name,
        channel_id=canvas.channel_id,
        kind=canvas.kind,
        template_id=canvas.template_id,
    )


def list_canvas_ids(team_id: int) -> Iterator[UUID]:
    """Every canvas id of the team and its environments, deleted ones included."""
    return Canvas.objects.for_team(team_id, canonical=True).values_list("id", flat=True).iterator()


def search_canvases(
    *,
    project_id: int,
    query: str | None,
    access_control: "UserAccessControl",
    limit: int,
    with_access_levels: bool,
    include_count: bool,
    viewer: CanvasViewer | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Ranked search over a project's standalone canvases, in the result shape of core search.

    Uses the canvas API's read rule: a canvas the viewer cannot open is left out. Without a `viewer`
    the caller is the access control's user, outside a sandbox. Canvases carry no access-control
    resource, so `user_access_level` is None.
    """
    # Imported on first use: the tasks app imports this module at `django.setup()`.
    from posthog.models.scoping.manager import resolve_effective_team_id  # noqa: PLC0415

    from products.canvas.backend.logic import search  # noqa: PLC0415

    if viewer is None:
        viewer = CanvasViewer(
            team_id=resolve_effective_team_id(project_id),
            user_id=access_control.user.id,
            sandboxed=False,
            sandbox_task_id=None,
        )
    rows, total_count = search.search(
        viewer=viewer,
        query=query,
        limit=limit,
        include_count=include_count,
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        result: dict[str, Any] = {
            "type": "canvas",
            "result_id": str(row["id"]),
            "extra_fields": {"name": row["name"]},
        }
        if query:
            result["rank"] = row["rank"]
        if with_access_levels:
            result["user_access_level"] = None
        results.append(result)
    return results, total_count
