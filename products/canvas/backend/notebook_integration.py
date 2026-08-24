from datetime import datetime
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.storage.object_storage import ObjectStorageError

from products.canvas.backend import build_service
from products.canvas.backend.artifacts import create_canvas_artifact_url
from products.canvas.backend.build_service import MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.source import (
    CANVAS_COMPONENT_PATH,
    has_errors,
    synthetic_source_project,
    validate_source_project,
)

_NOTEBOOK_CANVAS_NETWORK_DIAGNOSTICS = {"network_fetch", "network_xhr"}


@frozen
class CanvasGenerationState:
    canvas_id: UUID
    current_source_version_id: UUID | None
    published_build_id: UUID | None
    published_source_version_id: UUID | None
    published_artifact_url: str | None
    published_source_size: int | None
    published_artifact_size: int | None
    current_build_id: UUID | None
    current_build_status: str | None
    current_build_diagnostics: list[dict[str, object]]


@frozen
class NotebookCanvasSource:
    version_id: UUID
    source: str


@frozen
class NotebookCanvasVersion:
    id: UUID
    prompt: str | None
    created_at: datetime


class NotebookCanvasError(Exception):
    pass


class NotebookCanvasNotFoundError(NotebookCanvasError):
    pass


class NotebookCanvasVersionConflictError(NotebookCanvasError):
    pass


class NotebookCanvasBuildCapacityError(NotebookCanvasError):
    pass


class NotebookCanvasSourceUnavailableError(NotebookCanvasError):
    pass


class NotebookCanvasSourceInvalidError(NotebookCanvasError):
    pass


def create_notebook_canvas(*, team_id: int, user_id: int, channel_id: UUID, name: str, context: str) -> UUID:
    canvas = Canvas.objects.create(
        team_id=team_id,
        channel_id=channel_id,
        name=name,
        context=context,
        created_by_id=user_id,
    )
    return canvas.id


def update_notebook_canvas_generation(*, team_id: int, canvas_id: UUID, context: str) -> bool:
    return bool(
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False)
        .update(context=context, generation_task_id=None)
    )


def _notebook_canvas_project(source: str, input_names: list[str]) -> dict[str, Any]:
    project = synthetic_source_project(source)
    project["capabilities"] = {
        "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
        "network": {"origins": []},
        "notebook": {"frames": input_names},
    }
    return project


def validate_notebook_canvas_source(source: str, input_names: list[str]) -> list[dict[str, Any]]:
    diagnostics = validate_source_project(_notebook_canvas_project(source, input_names))
    return [
        {**diagnostic, "severity": "error"}
        if diagnostic.get("code") in _NOTEBOOK_CANVAS_NETWORK_DIAGNOSTICS
        else diagnostic
        for diagnostic in diagnostics
    ]


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

    project = _notebook_canvas_project(source, input_names)
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


def _canvas_generation_state(
    *, team_id: int, canvas_id: UUID, created_by_id: int | None = None
) -> CanvasGenerationState | None:
    canvases = Canvas.objects.for_team(team_id).select_related(
        "current_source_version", "published_build", "published_build__source_version"
    )
    if created_by_id is not None:
        canvases = canvases.filter(created_by_id=created_by_id)
    canvas = canvases.filter(id=canvas_id, deleted=False).first()
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
    artifact_size: int | None = None
    if (
        published_build is not None
        and published_build.status == CanvasBuild.STATUS_READY
        and published_build.artifact_object_prefix
        and isinstance(published_build.manifest, dict)
    ):
        entry = published_build.manifest.get("entryHtml")
        if isinstance(entry, str):
            artifact_url = create_canvas_artifact_url(published_build, entry)
        assets = published_build.manifest.get("assets")
        if isinstance(assets, list):
            sizes = [
                size for asset in assets if isinstance(asset, dict) if isinstance(size := asset.get("sizeBytes"), int)
            ]
            artifact_size = sum(sizes)

    return CanvasGenerationState(
        canvas_id=canvas.id,
        current_source_version_id=canvas.current_source_version_id,
        published_build_id=published_build.id if published_build else None,
        published_source_version_id=published_build.source_version_id if published_build else None,
        published_artifact_url=artifact_url,
        published_source_size=published_build.source_version.source_size if published_build else None,
        published_artifact_size=artifact_size,
        current_build_id=current_build.id if current_build else None,
        current_build_status=current_build.status if current_build else None,
        current_build_diagnostics=current_build.diagnostics if current_build else [],
    )


def get_canvas_generation_state(*, team_id: int, canvas_id: UUID) -> CanvasGenerationState | None:
    return _canvas_generation_state(team_id=team_id, canvas_id=canvas_id)


def get_owned_canvas_generation_state(*, team_id: int, canvas_id: UUID, user_id: int) -> CanvasGenerationState | None:
    return _canvas_generation_state(team_id=team_id, canvas_id=canvas_id, created_by_id=user_id)


def active_build_capacity_available(*, team_id: int) -> bool:
    active_builds = CanvasBuild.objects.for_team(team_id).filter(status__in=CanvasBuild.ACTIVE_STATUSES).count()
    return active_builds < MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM


def soft_delete_notebook_canvas(*, team_id: int, canvas_id: UUID) -> None:
    Canvas.objects.for_team(team_id).filter(id=canvas_id).update(deleted=True)


def get_notebook_canvas_source(
    *, team_id: int, canvas_id: UUID, version_id: UUID | None = None
) -> NotebookCanvasSource:
    canvas = Canvas.objects.for_team(team_id).filter(id=canvas_id, deleted=False).first()
    if canvas is None:
        raise NotebookCanvasNotFoundError
    resolved_version_id = version_id or canvas.current_source_version_id
    if resolved_version_id is None:
        raise NotebookCanvasNotFoundError
    version = (
        CanvasSourceVersion.objects.for_team(team_id)
        .filter(id=resolved_version_id, canvas_id=canvas.id, draft=False)
        .first()
    )
    if version is None:
        raise NotebookCanvasNotFoundError
    try:
        project = build_service.read_source_project(version)
    except ObjectStorageError as error:
        raise NotebookCanvasSourceUnavailableError from error
    files = project.get("files")
    source = files.get(CANVAS_COMPONENT_PATH) if isinstance(files, dict) else None
    if not isinstance(source, str):
        raise NotebookCanvasSourceUnavailableError
    return NotebookCanvasSource(version_id=version.id, source=source)


def list_notebook_canvas_versions(*, team_id: int, canvas_id: UUID) -> list[NotebookCanvasVersion]:
    canvas = Canvas.objects.for_team(team_id).filter(id=canvas_id, deleted=False).first()
    if canvas is None:
        raise NotebookCanvasNotFoundError
    return [
        NotebookCanvasVersion(id=version.id, prompt=version.prompt, created_at=version.created_at)
        for version in CanvasSourceVersion.objects.for_team(team_id)
        .filter(canvas_id=canvas.id, draft=False)
        .order_by("-created_at")[:100]
    ]


def restore_notebook_canvas_version(
    *, team_id: int, canvas_id: UUID, version_id: UUID, expected_current_version_id: UUID | None, user_id: int
) -> None:
    canvas = Canvas.objects.for_team(team_id).filter(id=canvas_id, deleted=False).first()
    if canvas is None:
        raise NotebookCanvasNotFoundError
    user = User.objects.filter(id=user_id).first()
    if user is None:
        raise NotebookCanvasNotFoundError
    try:
        build_service.revert_to_version(
            canvas,
            version_id,
            expected_current_version_id,
            user=user,
            was_impersonated=False,
        )
    except CanvasSourceVersion.DoesNotExist as error:
        raise NotebookCanvasNotFoundError from error
    except build_service.CanvasVersionConflict as error:
        raise NotebookCanvasVersionConflictError from error
    except build_service.CanvasBuildCapacityExceeded as error:
        raise NotebookCanvasBuildCapacityError from error
