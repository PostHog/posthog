import re
from datetime import datetime
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.storage.object_storage import ObjectStorageError

from products.canvas.backend import build_service
from products.canvas.backend.artifacts import create_canvas_artifact_url
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.source import has_errors, synthetic_source_project, validate_source_project

NOTEBOOK_FRAME_KEY_PREFIX = "__posthog_notebook_frame__:"

_READ_FRAME_RE = re.compile(r"\bph\s*\.\s*readFrame\s*\(\s*(?:[\"']([^\"']+)[\"'])?")
_NETWORK_DIAGNOSTICS = {"network_fetch", "network_xhr"}
_NAVIGATION_SINK_RE = re.compile(
    r"\b(?:window\s*\.\s*)?(?:location\s*(?:=|\.|\[)|open\s*\()|\b(?:document\s*\.\s*)?location\b"
)
_FRAME_BRIDGE = f"""
Object.assign(ph, {{
    readFrame: (name, options = {{}}) => ph.state.get(
        `{NOTEBOOK_FRAME_KEY_PREFIX}${{encodeURIComponent(name)}}:${{options.offset ?? 0}}:${{options.limit ?? 100}}`,
        {{ scope: "user" }}
    ),
}})
""".strip()


@frozen
class CanvasGenerationState:
    current_source_version_id: UUID | None
    published_source_version_id: UUID | None
    artifact_url: str | None
    build_status: str | None
    build_error: str | None


@frozen
class NotebookCanvasVersion:
    id: UUID
    parent_version_id: UUID | None
    prompt: str | None
    created_at: datetime
    build_status: str | None
    artifact_url: str | None


@frozen
class NotebookCanvasSource:
    version_id: UUID
    source: str


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
        source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET,
    ).id


def update_notebook_canvas(*, team_id: int, canvas_id: UUID, context: str) -> bool:
    return bool(
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET)
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
            "notebookFrames": True,
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
    if _NAVIGATION_SINK_RE.search(source):
        diagnostics.append(
            {
                "severity": "error",
                "code": "notebook_navigation_not_allowed",
                "message": "Notebook widgets cannot navigate or open browser windows.",
            }
        )
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
) -> tuple[UUID, UUID]:
    canvas = (
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET)
        .first()
    )
    user = User.objects.filter(id=user_id).first()
    if canvas is None or user is None:
        raise NotebookCanvasNotFoundError

    project = _source_project(source)
    if has_errors(validate_notebook_canvas_source(source, input_names)):
        raise NotebookCanvasSourceInvalidError

    try:
        _, version, build, _ = build_service.publish_source_project(
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
    return version.id, build.id


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
                parent_version_id=version.parent_version_id,
                prompt=version.prompt,
                created_at=version.created_at,
                build_status=current_build.status if current_build is not None else None,
                artifact_url=artifact_url,
            )
        )
    return result


def get_notebook_canvas_source(
    *, team_id: int, canvas_id: UUID, version_id: UUID | None = None
) -> NotebookCanvasSource:
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
    bridge_prefix = f"{_FRAME_BRIDGE}\n\n"
    return NotebookCanvasSource(
        version_id=version.id,
        source=source.removeprefix(bridge_prefix),
    )


def revert_notebook_canvas(
    *, team_id: int, canvas_id: UUID, version_id: UUID, expected_current_version_id: UUID | None, user_id: int
) -> UUID:
    canvas = (
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET)
        .first()
    )
    user = User.objects.filter(id=user_id).first()
    if canvas is None or user is None:
        raise NotebookCanvasNotFoundError
    try:
        _, build = build_service.revert_to_version(
            canvas,
            version_id,
            expected_current_version_id,
            user=user,
        )
    except CanvasSourceVersion.DoesNotExist as error:
        raise NotebookCanvasNotFoundError from error
    except build_service.CanvasVersionConflict as error:
        raise NotebookCanvasVersionConflictError from error
    except build_service.CanvasBuildCapacityExceeded as error:
        raise NotebookCanvasBuildCapacityError from error
    return build.id


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
        published_source_version_id=published_build.source_version_id if published_build else None,
        artifact_url=artifact_url,
        build_status=current_build.status if current_build else None,
        build_error=build_error,
    )
