"""Canvas source, versions, builds, and grid layout."""

from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet

from posthog.models.scoping import team_scope
from posthog.storage.object_storage import ObjectStorageError

from products.canvas.backend import build_service
from products.canvas.backend.facade.contracts import (
    CanvasBuildMove,
    CanvasBuildNotFoundError,
    CanvasBuildRecord,
    CanvasBuildsState,
    CanvasComponentLifecycle,
    CanvasDraftRecord,
    CanvasDraftResult,
    CanvasLayoutPublishResult,
    CanvasLayoutState,
    CanvasNotFoundError,
    CanvasOpenState,
    CanvasPublishResult,
    CanvasRecord,
    CanvasVersionNotFoundError,
    CanvasVersionRecord,
    CanvasViewer,
)
from products.canvas.backend.facade.enums import CanvasAccess
from products.canvas.backend.layout import default_layout
from products.canvas.backend.logic.access import authorized_canvases
from products.canvas.backend.logic.canvases import canvas_row, user_or_none
from products.canvas.backend.logic.records import (
    build_record,
    canvas_record,
    user_record,
    version_record,
    widening_record,
)
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion

# The canvas's build lifecycle returns this many recent builds (the published
# build is unioned in even when it has aged past the window).
BUILDS_WINDOW = 20
# Version-history window for the client's undo/revert browser.
VERSIONS_WINDOW = 100


def _version(team_id: int, canvas_id: UUID, version_id: str) -> CanvasSourceVersion:
    try:
        version = CanvasSourceVersion.objects.for_team(team_id).filter(pk=version_id, canvas_id=canvas_id).first()
    except ValidationError as error:
        raise CanvasVersionNotFoundError from error
    if version is None:
        raise CanvasVersionNotFoundError
    return version


def read_source(team_id: int, canvas_id: UUID, version_id: str | None) -> dict[str, Any]:
    """The head source project, or the project of `version_id`. Raises ObjectStorageError when storage fails."""
    if version_id:
        return build_service.read_source_project(_version(team_id, canvas_id, version_id))
    project, _ = build_service.current_source_project(canvas_row(team_id, canvas_id))
    return project


def head_source(team_id: int, canvas_id: UUID) -> tuple[dict[str, Any], str | None]:
    """The head source project and the head version id."""
    return build_service.current_source_project(canvas_row(team_id, canvas_id))


def list_versions(team_id: int, canvas_id: UUID) -> list[CanvasVersionRecord]:
    versions = (
        CanvasSourceVersion.objects.for_team(team_id)
        .filter(canvas_id=canvas_id, draft=False)
        .select_related("created_by")
        .order_by("-created_at")[:VERSIONS_WINDOW]
    )
    return [version_record(version) for version in versions]


def list_drafts(team_id: int, canvas_id: UUID) -> list[CanvasDraftRecord]:
    draft_versions = list(
        CanvasSourceVersion.objects.for_team(team_id)
        .filter(canvas_id=canvas_id, draft=True)
        .select_related("created_by")
        .order_by("-created_at")[:VERSIONS_WINDOW]
    )
    # Newest build per draft version. Only the id/status/version are needed,
    # so skip the heavy manifest/diagnostics JSON columns.
    latest_build_by_version: dict[Any, CanvasBuild] = {}
    for build in (
        CanvasBuild.objects.for_team(team_id)
        .filter(canvas_id=canvas_id, source_version_id__in=[version.id for version in draft_versions])
        .only("id", "source_version_id", "status")
        .order_by("source_version_id", "-created_at")
    ):
        latest_build_by_version.setdefault(build.source_version_id, build)
    drafts = []
    for version in draft_versions:
        latest = latest_build_by_version.get(version.id)
        drafts.append(
            CanvasDraftRecord(
                version_id=str(version.id),
                prompt=version.prompt,
                created_by=user_record(version.created_by),
                created_at=version.created_at,
                build_status=latest.status if latest else None,
                build_id=str(latest.id) if latest else None,
            )
        )
    return drafts


def publish_current_version(
    team_id: int, canvas_id: UUID, expected_current_version_id: UUID, *, user_id: int | None, was_impersonated: bool
) -> CanvasBuildMove:
    canvas, build = build_service.publish_current_source_version(
        canvas_row(team_id, canvas_id),
        expected_current_version_id,
        user=user_or_none(user_id),
        was_impersonated=was_impersonated,
    )
    return CanvasBuildMove(canvas=canvas_record(canvas), build=build_record(build))


def publish_source(
    team_id: int,
    canvas_id: UUID,
    *,
    project: dict[str, Any],
    prompt: str | None,
    name: str | None,
    has_expected_version: bool,
    expected_version_id: str | None,
    task_id: UUID | None,
    user_id: int | None,
    was_impersonated: bool,
) -> CanvasPublishResult:
    """Publish `project` as the new head and queue its build. The build in the result is not awaited."""
    canvas, version, build, first_publish = build_service.publish_source_project(
        canvas_row(team_id, canvas_id),
        project=project,
        prompt=prompt,
        name=name,
        has_expected_version=has_expected_version,
        expected_version_id=expected_version_id,
        task_id=task_id,
        created_by=user_or_none(user_id),
        was_impersonated=was_impersonated,
    )
    return CanvasPublishResult(
        canvas=canvas_record(canvas),
        version_id=version.id,
        version_capabilities=version.capabilities,
        source_size=version.source_size,
        build=build_record(build),
        first_publish=first_publish,
    )


def wait_for_build(team_id: int, canvas_id: UUID, build_id: UUID) -> CanvasBuildMove:
    """Wait a few seconds for the build to finish, then read the canvas again."""
    build = build_service.wait_for_build_result(CanvasBuild.objects.for_team(team_id).get(id=build_id))
    return CanvasBuildMove(canvas=canvas_record(canvas_row(team_id, canvas_id)), build=build_record(build))


def create_draft(
    team_id: int,
    canvas_id: UUID,
    *,
    project: dict[str, Any],
    prompt: str | None,
    task_id: UUID | None,
    user_id: int | None,
    was_impersonated: bool,
) -> CanvasDraftResult:
    version, build, widening = build_service.create_draft_version(
        canvas_row(team_id, canvas_id),
        project=project,
        prompt=prompt,
        task_id=task_id,
        created_by=user_or_none(user_id),
        was_impersonated=was_impersonated,
    )
    return CanvasDraftResult(
        version_id=version.id, build=build_record(build), capability_widening=widening_record(widening)
    )


def promote_draft(
    team_id: int,
    canvas_id: UUID,
    version_id: UUID,
    expected_current_version_id: UUID | None,
    *,
    user_id: int | None,
    was_impersonated: bool,
) -> CanvasBuildMove:
    try:
        canvas, build = build_service.promote_draft_version(
            canvas_row(team_id, canvas_id),
            version_id,
            expected_current_version_id,
            user=user_or_none(user_id),
            was_impersonated=was_impersonated,
        )
    except CanvasSourceVersion.DoesNotExist as error:
        raise CanvasVersionNotFoundError from error
    return CanvasBuildMove(canvas=canvas_record(canvas), build=build_record(build))


def revert(
    team_id: int,
    canvas_id: UUID,
    version_id: UUID,
    expected_current_version_id: UUID | None,
    *,
    user_id: int | None,
    was_impersonated: bool,
) -> CanvasBuildMove:
    try:
        canvas, build = build_service.revert_to_version(
            canvas_row(team_id, canvas_id),
            version_id,
            expected_current_version_id,
            user=user_or_none(user_id),
            was_impersonated=was_impersonated,
        )
    except CanvasSourceVersion.DoesNotExist as error:
        raise CanvasVersionNotFoundError from error
    return CanvasBuildMove(canvas=canvas_record(canvas), build=build_record(build))


def build_action(team_id: int, canvas_id: UUID, build_id: UUID, action: str) -> CanvasBuildRecord:
    """Retry, pin, unpin, or cancel one build. Raises ValueError when the action does not apply."""
    try:
        build = build_service.act_on_build(canvas_row(team_id, canvas_id), build_id, action)
    except CanvasBuild.DoesNotExist as error:
        raise CanvasBuildNotFoundError from error
    return build_record(build)


def canvas_builds(team_id: int, canvas_id: UUID, *, slim: bool, version_id: str | None) -> CanvasBuildsState:
    canvas = canvas_row(team_id, canvas_id)
    builds_queryset = CanvasBuild.objects.for_team(team_id).filter(canvas_id=canvas.id)
    if slim:
        # Pollers re-read this every couple of seconds; they need render
        # state, not 20 manifests of history.
        slim_q = Q(status__in=CanvasBuild.ACTIVE_STATUSES)
        if canvas.published_build_id:
            slim_q |= Q(id=canvas.published_build_id)
        if canvas.current_source_version_id:
            slim_q |= Q(source_version_id=canvas.current_source_version_id)
        builds = list(builds_queryset.filter(slim_q).order_by("-created_at")[:BUILDS_WINDOW])
    else:
        builds = list(builds_queryset.order_by("-created_at")[:BUILDS_WINDOW])
    # The live build must always be visible, even when newer (e.g. failed)
    # builds have pushed it past the window.
    if canvas.published_build_id and all(build.id != canvas.published_build_id for build in builds):
        published = builds_queryset.filter(id=canvas.published_build_id).first()
        if published is not None:
            builds.append(published)
    if version_id:
        try:
            requested_version = (
                CanvasSourceVersion.objects.for_team(team_id).filter(canvas_id=canvas.id, id=version_id).first()
            )
        except ValidationError:
            requested_version = None
        if requested_version is None:
            raise CanvasVersionNotFoundError
        historical_build = (
            builds_queryset.filter(source_version_id=requested_version.id, status=CanvasBuild.STATUS_READY)
            .order_by("-created_at")
            .first()
        )
        if historical_build is not None and all(build.id != historical_build.id for build in builds):
            builds.append(historical_build)
    return CanvasBuildsState(
        published_build_id=str(canvas.published_build_id) if canvas.published_build_id else None,
        current_version_id=str(canvas.current_source_version_id) if canvas.current_source_version_id else None,
        builds=[build_record(build) for build in builds],
    )


def _renderable_build(build: CanvasBuild | None) -> CanvasBuild | None:
    """The build if it can actually be served: ready, artifacts retained, and
    manifest frozen (the serializer needs the manifest to mint the entry URL)."""
    if (
        build is not None
        and build.status == CanvasBuild.STATUS_READY
        and build.artifact_object_prefix
        and isinstance(build.manifest, dict)
    ):
        return build
    return None


def _current_layout(canvas: Canvas) -> dict[str, Any]:
    """The canvas's head layout document, or the default empty layout before
    the first publish. Raises ObjectStorageError when storage is unavailable."""
    if canvas.current_source_version is None:
        return default_layout()
    return build_service.read_source_project(canvas.current_source_version)


def head_layout(team_id: int, canvas_id: UUID) -> dict[str, Any]:
    return _current_layout(canvas_row(team_id, canvas_id))


def _component_lifecycles(
    team_id: int, canvases: QuerySet[Canvas], layout: dict[str, Any]
) -> list[CanvasComponentLifecycle]:
    """The renderable build for each distinct (component, pinned version) the
    layout's live placements reference.

    The authorized queryset also enforces sandbox access. A component the
    caller may not read is omitted, identically to one that is missing."""
    placements = layout.get("placements")
    if not isinstance(placements, list):
        return []
    wanted: set[tuple[str, str | None]] = set()
    for placement in placements:
        if not isinstance(placement, dict) or placement.get("status") != "live":
            continue
        component = placement.get("component")
        if not isinstance(component, str):
            continue
        version = placement.get("version")
        pinned: str | None = None
        if isinstance(version, str) and version != "latest":
            try:
                pinned = str(UUID(version))
            except ValueError:
                continue
        try:
            component = str(UUID(component))
        except ValueError:
            continue
        wanted.add((component, pinned))
    if not wanted:
        return []

    component_ids = {component_id for component_id, _ in wanted}
    pinned_version_ids = {version_id for _, version_id in wanted if version_id}
    with team_scope(team_id):
        components = {
            str(canvas.id): canvas
            for canvas in canvases.filter(id__in=component_ids, kind=Canvas.KIND_COMPONENT).select_related(
                "published_build"
            )
        }
        pinned_builds: dict[str, CanvasBuild] = {}
        if pinned_version_ids:
            # One row per version (its newest ready build) instead of loading a
            # retry-loop's whole build history with manifests.
            for build in (
                CanvasBuild.objects.for_team(team_id)
                .filter(
                    source_version_id__in=pinned_version_ids,
                    canvas_id__in=components.keys(),
                    status=CanvasBuild.STATUS_READY,
                    artifact_object_prefix__isnull=False,
                )
                .order_by("source_version_id", "-created_at")
                .distinct("source_version_id")
            ):
                pinned_builds[str(build.source_version_id)] = build

    entries: list[CanvasComponentLifecycle] = []
    for component_id, pinned_version_id in sorted(wanted, key=lambda pair: (pair[0], pair[1] or "")):
        component_canvas = components.get(component_id)
        if component_canvas is None:
            continue
        if pinned_version_id:
            pinned_build = _renderable_build(pinned_builds.get(pinned_version_id))
            builds = [pinned_build] if pinned_build is not None and str(pinned_build.canvas_id) == component_id else []
        else:
            published = _renderable_build(component_canvas.published_build)
            builds = [published] if published is not None else []
        entries.append(
            CanvasComponentLifecycle(
                canvas_id=component_id,
                requested_version_id=pinned_version_id,
                published_build_id=(
                    str(component_canvas.published_build_id) if component_canvas.published_build_id else None
                ),
                current_version_id=(
                    str(component_canvas.current_source_version_id)
                    if component_canvas.current_source_version_id
                    else None
                ),
                builds=[build_record(build) for build in builds],
            )
        )
    return entries


def open_canvas(viewer: CanvasViewer, canvas_id: UUID | str) -> CanvasOpenState:
    canvases = authorized_canvases(viewer, CanvasAccess.READ)
    try:
        canvas = (
            canvases.select_related("created_by", "current_source_version", "published_build")
            .filter(id=canvas_id)
            .first()
        )
    except (ValueError, ValidationError):
        canvas = None
    if canvas is None:
        raise CanvasNotFoundError
    live_build = _renderable_build(canvas.published_build)
    newest_active = (
        CanvasBuild.objects.for_team(viewer.team_id)
        .filter(canvas_id=canvas.id, status__in=CanvasBuild.ACTIVE_STATUSES)
        .order_by("-created_at")
        .values_list("id", "status")
        .first()
    )
    source: dict[str, Any] | None = None
    layout: dict[str, Any] | None = None
    degraded = False
    # Object storage is read only when there is no artifact to render. A
    # storage hiccup degrades to the client's per-endpoint fallback instead
    # of failing the whole open.
    try:
        if canvas.kind == Canvas.KIND_GRID:
            layout = _current_layout(canvas)
        elif live_build is None:
            source, _ = build_service.current_source_project(canvas)
    except ObjectStorageError:
        degraded = True
    return CanvasOpenState(
        canvas=canvas_record(canvas),
        published_build=build_record(live_build) if live_build is not None else None,
        current_version_id=str(canvas.current_source_version_id) if canvas.current_source_version_id else None,
        has_active_build=newest_active is not None,
        source=source,
        layout=layout,
        component_lifecycles=_component_lifecycles(viewer.team_id, canvases, layout) if layout is not None else None,
        degraded=degraded,
    )


def read_layout(
    viewer: CanvasViewer, canvas: CanvasRecord, *, version_id: str | None, include_components: bool
) -> CanvasLayoutState:
    """The head layout, or the layout of `version_id`. Raises ObjectStorageError when storage fails."""
    if version_id:
        layout = build_service.read_source_project(_version(viewer.team_id, canvas.id, version_id))
    else:
        layout = head_layout(viewer.team_id, canvas.id)
    lifecycles = (
        _component_lifecycles(viewer.team_id, authorized_canvases(viewer, CanvasAccess.READ), layout)
        if include_components
        else None
    )
    return CanvasLayoutState(layout=layout, component_lifecycles=lifecycles)


def publish_layout(
    team_id: int,
    canvas_id: UUID,
    *,
    layout: dict[str, Any],
    prompt: str | None,
    has_expected_version: bool,
    expected_version_id: str | None,
    task_id: UUID | None,
    user_id: int | None,
    was_impersonated: bool,
) -> CanvasLayoutPublishResult:
    canvas, version = build_service.publish_grid_layout(
        canvas_row(team_id, canvas_id),
        layout=layout,
        prompt=prompt,
        has_expected_version=has_expected_version,
        expected_version_id=expected_version_id,
        task_id=task_id,
        created_by=user_or_none(user_id),
        was_impersonated=was_impersonated,
    )
    return CanvasLayoutPublishResult(canvas=canvas_record(canvas), version_id=version.id)
