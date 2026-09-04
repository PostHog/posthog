"""What the generic sharing API needs from canvases: who may share one, and what a
public link serves.

Sharing rides channel visibility in v1: a canvas can be shared by anyone who can
see it, which by the channel rule is everyone in the project for a public space
and only the owner for a personal space. Per-object access control layers on
top later without changing this boundary.
"""

from typing import Any

from products.canvas.backend.artifacts import create_canvas_artifact_url
from products.canvas.backend.models import Canvas, CanvasBuild
from products.tasks.backend.facade import api as tasks_facade

# The kinds a public link can render on its own. A grid is a composition that
# loads its components live through the host, which the shared page cannot do.
SHAREABLE_KINDS = frozenset({Canvas.KIND_FREEFORM, Canvas.KIND_COMPONENT})


def user_can_access_canvas(*, team_id: int, user_id: int | None, canvas_id: Any) -> bool:
    return (
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_STANDARD)
        .filter(tasks_facade.visible_channels_q(user_id, relation="channel"))
        .exists()
    )


def canvas_is_shareable(canvas: Canvas) -> bool:
    return not canvas.deleted and canvas.kind in SHAREABLE_KINDS


def _published_ready_build(canvas: Canvas) -> CanvasBuild | None:
    build = canvas.published_build
    if (
        build is None
        or build.status != CanvasBuild.STATUS_READY
        or not build.artifact_object_prefix
        or not isinstance(build.manifest, dict)
    ):
        return None
    return build


def shared_canvas_payload(canvas: Canvas) -> dict[str, Any]:
    """The public page's view of a canvas. The artifact URL is a fresh signed
    capability minted for this page load; it is only handed out after the share
    token (and any password) has been validated by the caller."""
    build = _published_ready_build(canvas)
    entry = build.manifest.get("entryHtml") if build is not None and isinstance(build.manifest, dict) else None
    artifact_url = create_canvas_artifact_url(build, entry) if build is not None and isinstance(entry, str) else None
    return {
        "id": str(canvas.id),
        "name": canvas.name,
        "kind": canvas.kind,
        "description": canvas.description,
        "published": build is not None,
        "artifact_url": artifact_url,
    }
