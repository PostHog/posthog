from uuid import UUID

from posthog.dataclasses import frozen

from products.canvas.backend.artifacts import create_canvas_artifact_url
from products.canvas.backend.build_service import MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM
from products.canvas.backend.models import Canvas, CanvasBuild


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


def create_notebook_canvas(
    *, team_id: int, user_id: int, channel_id: UUID, name: str, context: str, generation_task_id: UUID
) -> UUID:
    canvas = Canvas.objects.create(
        team_id=team_id,
        channel_id=channel_id,
        name=name,
        context=context,
        generation_task_id=generation_task_id,
        created_by_id=user_id,
    )
    return canvas.id


def update_notebook_canvas_generation(*, team_id: int, canvas_id: UUID, context: str, generation_task_id: UUID) -> bool:
    return bool(
        Canvas.objects.for_team(team_id)
        .filter(id=canvas_id, deleted=False)
        .update(context=context, generation_task_id=generation_task_id)
    )


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
