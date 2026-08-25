import re
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models import User

from products.canvas.backend import build_service
from products.canvas.backend.artifacts import create_canvas_artifact_url
from products.canvas.backend.models import Canvas, CanvasBuild
from products.canvas.backend.source import has_errors, synthetic_source_project, validate_source_project

NOTEBOOK_FRAME_KEY_PREFIX = "__posthog_notebook_frame__:"

_READ_FRAME_RE = re.compile(r"\bph\s*\.\s*readFrame\s*\(\s*(?:[\"']([^\"']+)[\"'])?")
_NETWORK_DIAGNOSTICS = {"network_fetch", "network_xhr"}
_FRAME_BRIDGE = f"""
Object.assign(ph, {{
    readFrame: (name) => ph.state.get(`{NOTEBOOK_FRAME_KEY_PREFIX}${{name}}`, {{ scope: "user" }}),
}})
""".strip()


@frozen
class CanvasGenerationState:
    current_source_version_id: UUID | None
    published_source_version_id: UUID | None
    artifact_url: str | None
    build_status: str | None


class NotebookCanvasError(Exception):
    pass


class NotebookCanvasNotFoundError(NotebookCanvasError):
    pass


class NotebookCanvasVersionConflictError(NotebookCanvasError):
    pass


class NotebookCanvasBuildCapacityError(NotebookCanvasError):
    pass


class NotebookCanvasSourceInvalidError(NotebookCanvasError):
    pass


def create_notebook_canvas(*, team_id: int, user_id: int, channel_id: UUID, name: str, context: str) -> UUID:
    return Canvas.objects.create(
        team_id=team_id,
        channel_id=channel_id,
        name=name,
        context=context,
        created_by_id=user_id,
    ).id


def update_notebook_canvas(*, team_id: int, canvas_id: UUID, context: str) -> bool:
    return bool(
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False)
        .update(context=context, generation_task_id=None)
    )


def _source_project(source: str) -> dict[str, Any]:
    project = synthetic_source_project(f"{_FRAME_BRIDGE}\n\n{source}")
    project["capabilities"] = {
        "posthog": {
            "insights": [],
            "inlineQueries": False,
            "captureEvents": [],
            "state": ["user"],
        },
        "network": {"origins": []},
    }
    return project


def validate_notebook_canvas_source(source: str, input_names: list[str]) -> list[dict[str, Any]]:
    allowed_frames = set(input_names)
    diagnostics = validate_source_project(_source_project(source))
    diagnostics = [
        {**diagnostic, "severity": "error"} if diagnostic.get("code") in _NETWORK_DIAGNOSTICS else diagnostic
        for diagnostic in diagnostics
    ]
    for match in _READ_FRAME_RE.finditer(source):
        frame_name = match.group(1)
        if frame_name is None:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "notebook_frame_must_be_literal",
                    "message": "ph.readFrame() requires a literal dataframe name.",
                }
            )
        elif frame_name not in allowed_frames:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "notebook_frame_not_allowed",
                    "message": f'Dataframe "{frame_name}" is not available to this visualization.',
                }
            )
    return diagnostics


def publish_notebook_canvas_source(
    *,
    team_id: int,
    canvas_id: UUID,
    user_id: int,
    source: str,
    input_names: list[str],
    prompt: str,
    name: str,
    expected_current_version_id: UUID | None,
) -> None:
    canvas = Canvas.objects.for_team(team_id).filter(id=canvas_id, deleted=False).first()
    user = User.objects.filter(id=user_id).first()
    if canvas is None or user is None:
        raise NotebookCanvasNotFoundError

    project = _source_project(source)
    if has_errors(validate_notebook_canvas_source(source, input_names)):
        raise NotebookCanvasSourceInvalidError

    try:
        build_service.publish_source_project(
            canvas,
            project=project,
            prompt=prompt,
            name=name,
            has_expected_version=True,
            expected_version_id=str(expected_current_version_id) if expected_current_version_id else None,
            task_id=None,
            created_by=user,
        )
    except build_service.CanvasVersionConflict as error:
        raise NotebookCanvasVersionConflictError from error
    except build_service.CanvasBuildCapacityExceeded as error:
        raise NotebookCanvasBuildCapacityError from error


def get_canvas_generation_state(*, team_id: int, canvas_id: UUID) -> CanvasGenerationState | None:
    canvas = (
        Canvas.objects.for_team(team_id)
        .select_related("published_build", "published_build__source_version")
        .filter(id=canvas_id, deleted=False)
        .first()
    )
    if canvas is None:
        return None

    current_build = (
        CanvasBuild.objects.for_team(team_id)
        .filter(canvas_id=canvas.id, source_version_id=canvas.current_source_version_id)
        .order_by("-created_at")
        .first()
        if canvas.current_source_version_id
        else None
    )
    published_build = canvas.published_build
    artifact_url: str | None = None
    if (
        published_build is not None
        and published_build.status == CanvasBuild.STATUS_READY
        and published_build.artifact_object_prefix
        and isinstance(published_build.manifest, dict)
        and isinstance(entry := published_build.manifest.get("entryHtml"), str)
    ):
        artifact_url = create_canvas_artifact_url(published_build, entry)

    return CanvasGenerationState(
        current_source_version_id=canvas.current_source_version_id,
        published_source_version_id=published_build.source_version_id if published_build else None,
        artifact_url=artifact_url,
        build_status=current_build.status if current_build else None,
    )
