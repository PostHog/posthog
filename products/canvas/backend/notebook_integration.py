from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.storage.object_storage import ObjectStorageError

from products.canvas.backend import build_service
from products.canvas.backend.artifacts import create_canvas_artifact_url
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.source import has_errors, synthetic_source_project, validate_source_project
from products.tasks.backend.facade import api as tasks_facade

_NETWORK_DIAGNOSTICS = {"network_fetch", "network_xhr"}
_LEGACY_FRAME_BRIDGE_START = "/* __POSTHOG_NOTEBOOK_BRIDGE_START__ */"
_LEGACY_FRAME_BRIDGE_END = "/* __POSTHOG_NOTEBOOK_BRIDGE_END__ */"


@frozen
class CanvasGenerationState:
    current_source_version_id: UUID | None
    artifact_url: str | None
    build_status: str | None
    build_error: str | None
    build_hash: str | None = None


@frozen
class NotebookCanvasVersion:
    id: UUID
    build_status: str | None
    artifact_url: str | None
    build_hash: str | None = None


@frozen
class PreparedNotebookCanvasSource:
    canvas_id: UUID
    expected_current_version_id: UUID | None
    prompt: str
    name: str
    prepared: build_service.PreparedSourceProjectPublish


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
    if not tasks_facade.channel_exists(team_id, channel_id, user_id):
        raise NotebookCanvasNotFoundError
    return (
        Canvas.objects.for_team(team_id)
        .create(
            team_id=team_id,
            channel_id=channel_id,
            name=name,
            context=context,
            created_by_id=user_id,
            source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET,
        )
        .id
    )


def _source_project(source: str, input_names: list[str]) -> dict[str, Any]:
    project = synthetic_source_project(source)
    files = project["files"]
    if isinstance(files, dict) and isinstance(index_html := files.get("index.html"), str):
        files["index.html"] = index_html.replace(
            "</head>",
            "<style>html,body,#root{width:100%;height:100%;margin:0}</style></head>",
        )
    project["capabilities"] = {
        "posthog": {
            "insights": [],
            "inlineQueries": False,
            "captureEvents": [],
            "state": ["user"],
            "notebookFrames": list(input_names),
        },
        "network": {"origins": []},
    }
    return project


def _strip_legacy_frame_bridge(source: str) -> str:
    if source.startswith(_LEGACY_FRAME_BRIDGE_START):
        _, separator, user_source = source.partition(_LEGACY_FRAME_BRIDGE_END)
        if separator:
            return user_source.removeprefix("\n\n")
    return source


def validate_notebook_canvas_source(source: str, input_names: list[str]) -> list[dict[str, Any]]:
    return [
        {**diagnostic, "severity": "error"} if diagnostic.get("code") in _NETWORK_DIAGNOSTICS else diagnostic
        for diagnostic in validate_source_project(_source_project(source, input_names))
    ]


def prepare_notebook_canvas_source(
    *,
    team_id: int,
    canvas_id: UUID,
    user_id: int,
    source: str,
    input_names: list[str],
    prompt: str,
    name: str,
    expected_current_version_id: UUID | None,
) -> PreparedNotebookCanvasSource:
    canvas = (
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET)
        .first()
    )
    if canvas is None or not User.objects.filter(id=user_id).exists():
        raise NotebookCanvasNotFoundError

    project = _source_project(source, input_names)
    if has_errors(validate_notebook_canvas_source(source, input_names)):
        raise NotebookCanvasSourceInvalidError

    try:
        prepared = build_service.prepare_source_project_publish(
            canvas,
            project=project,
            has_expected_version=True,
            expected_version_id=str(expected_current_version_id) if expected_current_version_id else None,
        )
    except build_service.CanvasVersionConflict as error:
        raise NotebookCanvasVersionConflictError from error
    except build_service.CanvasBuildCapacityExceeded as error:
        raise NotebookCanvasBuildCapacityError from error
    except ObjectStorageError as error:
        raise NotebookCanvasError from error
    return PreparedNotebookCanvasSource(
        canvas_id=canvas.id,
        expected_current_version_id=expected_current_version_id,
        prompt=prompt,
        name=name,
        prepared=prepared,
    )


def publish_prepared_notebook_canvas_source(
    *, team_id: int, user_id: int, prepared: PreparedNotebookCanvasSource
) -> UUID:
    canvas = (
        Canvas.objects.for_team(team_id)
        .filter(id=prepared.canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET)
        .first()
    )
    user = User.objects.filter(id=user_id).first()
    if canvas is None or user is None:
        raise NotebookCanvasNotFoundError
    try:
        result = build_service.commit_source_project_publish(
            canvas,
            prepared=prepared.prepared,
            prompt=prepared.prompt,
            name=prepared.name,
            has_expected_version=True,
            expected_version_id=(
                str(prepared.expected_current_version_id) if prepared.expected_current_version_id else None
            ),
            task_id=None,
            created_by=user,
        )
    except build_service.CanvasVersionConflict as error:
        raise NotebookCanvasVersionConflictError from error
    except build_service.CanvasBuildCapacityExceeded as error:
        raise NotebookCanvasBuildCapacityError from error
    except ObjectStorageError as error:
        raise NotebookCanvasError from error
    return result.version.id


def list_notebook_canvas_versions(
    *, team_id: int, canvas_id: UUID, version_ids: list[UUID] | None = None
) -> list[NotebookCanvasVersion]:
    canvas = (
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET)
        .first()
    )
    if canvas is None:
        raise NotebookCanvasNotFoundError
    versions_queryset = CanvasSourceVersion.objects.for_team(team_id).filter(canvas_id=canvas.id, draft=False)
    builds_queryset = CanvasBuild.objects.for_team(team_id).filter(canvas_id=canvas.id)
    if version_ids is not None:
        versions_queryset = versions_queryset.filter(id__in=version_ids)
        builds_queryset = builds_queryset.filter(source_version_id__in=version_ids)
    versions = list(versions_queryset.order_by("created_at"))
    builds = builds_queryset.order_by("-created_at")
    latest_builds: dict[UUID, CanvasBuild] = {}
    latest_ready_builds: dict[UUID, CanvasBuild] = {}
    for build_record in builds:
        latest_builds.setdefault(build_record.source_version_id, build_record)
        if build_record.status == CanvasBuild.STATUS_READY:
            latest_ready_builds.setdefault(build_record.source_version_id, build_record)

    result: list[NotebookCanvasVersion] = []
    for version in versions:
        current_build = latest_builds.get(version.id)
        ready_build = latest_ready_builds.get(version.id)
        artifact_url: str | None = None
        if (
            ready_build is not None
            and ready_build.artifact_object_prefix
            and isinstance(ready_build.manifest, dict)
            and isinstance(entry := ready_build.manifest.get("entryHtml"), str)
        ):
            artifact_url = create_canvas_artifact_url(ready_build, entry)
        result.append(
            NotebookCanvasVersion(
                id=version.id,
                build_status=current_build.status if current_build is not None else None,
                artifact_url=artifact_url,
                build_hash=ready_build.integrity if ready_build is not None else None,
            )
        )
    return result


def get_notebook_canvas_source(*, team_id: int, canvas_id: UUID, version_id: UUID | None = None) -> str:
    canvas = (
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET)
        .first()
    )
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
        raise NotebookCanvasError from error
    files = project.get("files")
    source = files.get("src/canvas.tsx") if isinstance(files, dict) else None
    if not isinstance(source, str):
        raise NotebookCanvasSourceInvalidError
    return _strip_legacy_frame_bridge(source)


def get_canvas_generation_state(*, team_id: int, canvas_id: UUID) -> CanvasGenerationState | None:
    canvas = (
        Canvas.objects.for_team(team_id)
        .select_related("published_build", "published_build__source_version")
        .filter(id=canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET)
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

    build_error: str | None = None
    if current_build is not None and isinstance(current_build.diagnostics, list):
        for diagnostic in current_build.diagnostics:
            if isinstance(diagnostic, dict) and isinstance(message := diagnostic.get("message"), str):
                build_error = message[:1_000]
                break

    return CanvasGenerationState(
        current_source_version_id=canvas.current_source_version_id,
        artifact_url=artifact_url,
        build_status=current_build.status if current_build else None,
        build_error=build_error,
        build_hash=published_build.integrity if published_build is not None else None,
    )
