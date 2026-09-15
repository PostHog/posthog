"""What the generic sharing API needs from canvases: who may share one, which
build a public link is pinned to, and what that link serves.

Sharing rides channel visibility in v1: a canvas can be shared by anyone who can
see it, which by the channel rule is everyone in the project for a public space
and only the owner for a personal space. Per-object access control layers on
top later without changing this boundary.

A public link is a capture. Turning sharing on pins the build published at that
moment, and a later publish never changes what the link shows until sharing is
turned on again.
"""

from typing import Any

from products.canvas.backend.artifacts import create_canvas_artifact_url
from products.canvas.backend.build_service import CanvasNotPublished
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


def _ready_build(build: CanvasBuild | None) -> CanvasBuild | None:
    if (
        build is None
        or build.status != CanvasBuild.STATUS_READY
        or not build.artifact_object_prefix
        or not isinstance(build.manifest, dict)
    ):
        return None
    return build


def canvas_has_ready_build(canvas: Canvas) -> bool:
    return _ready_build(canvas.published_build) is not None


def pin_shared_build(canvas: Canvas) -> CanvasBuild:
    """Point the public link at the build that is published right now. Raises
    ``CanvasNotPublished`` when there is nothing ready to capture."""
    build = _ready_build(canvas.published_build)
    if build is None:
        raise CanvasNotPublished()
    canvas.shared_build = build
    canvas.save(update_fields=["shared_build", "updated_at"])
    return build


def clear_shared_build(canvas: Canvas) -> None:
    if canvas.shared_build_id is None:
        return
    canvas.shared_build = None
    canvas.save(update_fields=["shared_build", "updated_at"])


def shared_canvas_payload(canvas: Canvas) -> dict[str, Any]:
    """The public page's view of a canvas: the build pinned when sharing was
    turned on. The artifact URL is a fresh signed capability minted for this
    page load; it is only handed out after the share token (and any password)
    has been validated by the caller."""
    build = _ready_build(canvas.shared_build)
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
