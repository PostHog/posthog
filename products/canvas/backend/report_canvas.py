import gzip
import json
from typing import Literal
from uuid import UUID

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.canvas.backend.build_service import read_source_project
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion


@frozen
class CanvasGenerationState:
    status: Literal["waiting_for_source", "building", "ready", "failed"]
    failure_reason: str = ""
    source_version_id: UUID | None = None


@frozen
class CanvasGenerationSource:
    project: dict[str, object]
    storage_key: str
    source_hash: str


class CanvasGenerationSourceUnavailable(Exception):
    pass


def create_report_canvas(*, team_id: int, channel_id: str | UUID, name: str, discussion_task_id: str | UUID) -> UUID:
    canvas = Canvas.objects.for_team(team_id).create(
        team_id=team_id,
        channel_id=channel_id,
        name=name,
        discussion_task_id=discussion_task_id,
    )
    return canvas.id


def set_generation_task(*, team_id: int, canvas_id: str | UUID, task_id: str | UUID) -> None:
    updated = Canvas.objects.for_team(team_id).filter(id=canvas_id).update(generation_task_id=task_id)
    if updated != 1:
        raise Canvas.DoesNotExist(canvas_id)


def get_canvas_channel_id(*, team_id: int, canvas_id: str | UUID) -> UUID:
    return Canvas.objects.for_team(team_id).values_list("channel_id", flat=True).get(id=canvas_id)


def set_canvas_name(*, team_id: int, canvas_id: str | UUID, name: str) -> None:
    updated = Canvas.objects.for_team(team_id).filter(id=canvas_id).update(name=name, updated_at=timezone.now())
    if updated != 1:
        raise Canvas.DoesNotExist(canvas_id)


def canvas_generation_result(*, team_id: int, canvas_id: str | UUID, task_id: str | UUID) -> CanvasGenerationState:
    canvas = Canvas.objects.for_team(team_id).get(id=canvas_id)
    source_version = (
        CanvasSourceVersion.objects.for_team(team_id)
        .filter(canvas=canvas, task_id=task_id)
        .order_by("-created_at")
        .first()
    )
    if source_version is None:
        return CanvasGenerationState(status="waiting_for_source")

    build = CanvasBuild.objects.for_team(team_id).filter(source_version=source_version).order_by("-created_at").first()
    if build is None or build.status in CanvasBuild.ACTIVE_STATUSES:
        return CanvasGenerationState(status="building")
    if build.status == CanvasBuild.STATUS_READY:
        return CanvasGenerationState(status="ready", source_version_id=source_version.id)

    messages = [
        str(diagnostic.get("message"))
        for diagnostic in build.diagnostics
        if isinstance(diagnostic, dict) and diagnostic.get("message")
    ]
    reason = messages[0] if messages else "The canvas build failed."
    return CanvasGenerationState(status="failed", failure_reason=reason)


def canvas_generation_source(
    *, team_id: int, canvas_id: str | UUID, source_version_id: str | UUID
) -> CanvasGenerationSource:
    try:
        version = CanvasSourceVersion.objects.for_team(team_id).get(
            id=source_version_id,
            canvas_id=canvas_id,
        )
        return CanvasGenerationSource(
            project=read_source_project(version),
            storage_key=version.source_object_key,
            source_hash=version.source_hash,
        )
    except (
        CanvasSourceVersion.DoesNotExist,
        object_storage.ObjectStorageError,
        gzip.BadGzipFile,
        EOFError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise CanvasGenerationSourceUnavailable from error
