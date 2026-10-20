from __future__ import annotations

from typing import Any

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.canvas.backend.facade import api as canvas_facade
from products.canvas.backend.facade.contracts import CanvasNotFoundError, CanvasViewer
from products.canvas.backend.facade.enums import CanvasAccess
from products.dashboards.backend.widget_specs.configs import CANVAS_APP_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config


def run_canvas_app_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    # Part of the shared run_widgets runner signature (always passed by the dispatcher).
    include_total_count: bool = True,
) -> dict[str, Any]:
    """Resolve the canvas a tile points at, as the viewer.

    The tile itself renders the canvas's live build through the canvas API with the viewer's own
    session, so this runner only answers "may this viewer see this canvas, and which one is it".
    Space visibility and object-level access controls both apply, exactly as on the canvas scene.
    """
    typed_config = validate_widget_config(CANVAS_APP_WIDGET_TYPE, config)
    canvas_id = typed_config.get("canvasId")
    viewer = CanvasViewer(
        team_id=team.id, user_id=user.id if user is not None else None, sandboxed=False, sandbox_task_id=None
    )
    if canvas_id is None:
        # Same canvases the tile's picker offers, so the tile can offer "New canvas" when there are none.
        visible_canvases = canvas_facade.count_canvases(
            viewer,
            channel_id=None,
            kind="freeform",
            search=None,
            user_access_control=UserAccessControl(user=user, team=team) if user is not None else None,
            include_all_if_admin=False,
        )
        return {"canvas": None, "needsConfiguration": True, "hasCanvases": visible_canvases > 0}

    try:
        canvas = canvas_facade.get_canvas(viewer, CanvasAccess.READ, canvas_id)
    except CanvasNotFoundError:
        return {"canvas": None, "canvasNotFound": True}
    if user is not None:
        ref = ObjectAccessRef(
            resource="canvas", id=str(canvas.id), team_id=canvas.team_id, created_by_id=canvas.created_by_id
        )
        if not UserAccessControl(user=user, team=team).check_access_level_for_ref(ref, "viewer"):
            return {"canvas": None, "canvasNotFound": True}

    return {
        "canvas": {
            "id": str(canvas.id),
            "name": canvas.name,
            "spaceId": str(canvas.channel_id),
            "publishedBuildId": str(canvas.published_build_id) if canvas.published_build_id else None,
            "currentVersionId": str(canvas.current_source_version_id) if canvas.current_source_version_id else None,
        }
    }
