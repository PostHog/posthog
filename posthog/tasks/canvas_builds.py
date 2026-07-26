from __future__ import annotations

import json
import base64
import hashlib
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models.file_system.canvas import CanvasApplication, CanvasBuild, CanvasSourceVersion
from posthog.models.file_system.file_system import FileSystem
from posthog.storage import object_storage

from products.tasks.backend.facade import api as tasks_facade

MAX_ARTIFACT_FILES = 512
MAX_ARTIFACT_BYTES = 20_000_000
BUILDER_PATH = Path(settings.BASE_DIR) / "common" / "canvas-builder" / "build.mjs"


def _valid_artifact_path(value: str) -> bool:
    segments = value.split("/")
    return (
        bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and all(segment not in {"", ".", ".."} for segment in segments)
    )


def _run_builder(project: dict[str, Any]) -> dict[str, Any]:
    process = subprocess.run(
        ["node", "--max-old-space-size=256", str(BUILDER_PATH)],
        input=json.dumps({"project": project}, separators=(",", ":")),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=settings.BASE_DIR,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "NODE_ENV": "production"},
    )
    if process.returncode != 0:
        raise RuntimeError("Canvas builder process failed")
    result = json.loads(process.stdout)
    if not isinstance(result, dict):
        raise ValueError("Canvas builder returned an invalid response")
    return result


def _validated_artifacts(result: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, Any]]:
    artifact_files = result.get("artifactFiles")
    manifest = result.get("manifest")
    if not isinstance(artifact_files, dict) or not isinstance(manifest, dict):
        raise ValueError("Canvas builder omitted artifacts or manifest")
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list) or len(manifest_files) > MAX_ARTIFACT_FILES:
        raise ValueError("Canvas artifact manifest has too many files")
    declared: dict[str, dict[str, Any]] = {}
    for entry in manifest_files:
        if not isinstance(entry, dict):
            raise ValueError("Canvas artifact manifest contains an invalid file")
        path = entry.get("path")
        content_type = entry.get("contentType")
        size = entry.get("bytes")
        digest = entry.get("sha256")
        if (
            not isinstance(path, str)
            or not _valid_artifact_path(path)
            or not isinstance(content_type, str)
            or not content_type
            or "\n" in content_type
            or "\r" in content_type
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or path in declared
        ):
            raise ValueError("Canvas artifact manifest contains an invalid file")
        declared[path] = entry
    if len(declared) != len(manifest_files) or set(declared) != set(artifact_files):
        raise ValueError("Canvas artifact manifest does not match emitted files")
    encoded: dict[str, bytes] = {}
    total = 0
    for path, content in artifact_files.items():
        if not isinstance(path, str) or not _valid_artifact_path(path) or not isinstance(content, str):
            raise ValueError("Canvas builder emitted an invalid artifact")
        data = content.encode()
        entry = declared[path]
        if entry.get("sha256") != hashlib.sha256(data).hexdigest() or entry.get("bytes") != len(data):
            raise ValueError("Canvas artifact integrity does not match its manifest")
        total += len(data)
        encoded[path] = data
    if total > MAX_ARTIFACT_BYTES:
        raise ValueError("Canvas build exceeds the artifact size limit")
    if manifest.get("entryHtml") != "index.html" or "index.html" not in encoded:
        raise ValueError("Canvas build does not contain index.html")
    return encoded, manifest


def validate_canvas_project(project: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _run_builder(project)
        diagnostics = result.get("diagnostics")
        bounded_diagnostics = diagnostics[:500] if isinstance(diagnostics, list) else []
        if result.get("ok") is not True:
            return {
                "ok": False,
                "diagnostics": bounded_diagnostics,
                "manifest": None,
            }
        _, manifest = _validated_artifacts(result)
        return {
            "ok": True,
            "diagnostics": bounded_diagnostics,
            "manifest": manifest,
        }
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, RuntimeError, ValueError):
        return {
            "ok": False,
            "diagnostics": [
                {
                    "severity": "error",
                    "code": "validation_unavailable",
                    "message": "Canvas validation is temporarily unavailable.",
                }
            ],
            "manifest": None,
        }


def _complete_build(build: CanvasBuild, artifacts: dict[str, bytes], manifest: dict[str, Any]) -> None:
    prefix = f"canvas/artifacts/{build.team_id}/{build.id}"
    manifest_files = {entry["path"]: entry for entry in manifest["files"]}
    for path, content in artifacts.items():
        object_storage.write(
            f"{prefix}/{path}",
            content,
            extras={
                "ContentType": manifest_files[path]["contentType"],
                "CacheControl": "private, max-age=31536000, immutable",
            },
        )
    integrity = "sha256-" + base64.b64encode(hashlib.sha256(artifacts["index.html"]).digest()).decode()

    with transaction.atomic():
        locked = CanvasBuild.objects.for_team(build.team_id).select_for_update().get(id=build.id)
        application = (
            CanvasApplication.objects.for_team(build.team_id).select_for_update().get(canvas_id=build.canvas_id)
        )
        locked.build_status = CanvasBuild.Status.READY
        locked.artifact_object_prefix = prefix
        locked.integrity = integrity
        locked.diagnostics = []
        locked.manifest = manifest
        locked.completed_at = timezone.now()
        locked.save(
            update_fields=[
                "build_status",
                "artifact_object_prefix",
                "integrity",
                "diagnostics",
                "manifest",
                "completed_at",
            ]
        )
        if application.current_source_version_id != locked.source_version_id:
            return
        application.previous_build_id = application.active_build_id
        application.active_build = locked
        application.save(update_fields=["previous_build", "active_build", "updated_at"])
        canvas = FileSystem.objects.select_for_update().get(id=build.canvas_id, team_id=build.team_id)
        meta = dict(canvas.meta or {})
        meta.update({"activeBuildId": str(locked.id), "currentSourceVersionId": str(locked.source_version_id)})
        canvas.meta = meta
        canvas.save(update_fields=["meta"])
    _post_build_update(build, "ready")


def _fail_build(build: CanvasBuild, diagnostics: list[dict[str, Any]]) -> None:
    CanvasBuild.objects.for_team(build.team_id).filter(id=build.id).update(
        build_status=CanvasBuild.Status.FAILED,
        diagnostics=diagnostics[:500],
        completed_at=timezone.now(),
    )
    _post_build_update(build, "failed")


def _post_build_update(build: CanvasBuild, build_status: Literal["ready", "failed"]) -> None:
    source = build.source_version
    canvas = build.canvas
    channel_id = (canvas.meta or {}).get("channelId")
    canvas_url = f"{settings.SITE_URL}/code/canvas/{channel_id}/{canvas.id}" if channel_id else None
    tasks_facade.post_canvas_build_thread_update(
        source.task_id,
        build.team_id,
        acting_user_id=source.created_by_id,
        canvas_name=canvas.path.rsplit("/", 1)[-1] or "Canvas",
        canvas_url=canvas_url,
        build_id=build.id,
        source_version_id=source.id,
        build_status=build_status,
    )
    if source.parent_version_id is None and build_status == "ready":
        tasks_facade.post_canvas_created_thread_update(
            source.task_id,
            build.team_id,
            acting_user_id=source.created_by_id,
            canvas_name=canvas.path.rsplit("/", 1)[-1] or "Canvas",
            canvas_url=canvas_url,
        )


@shared_task(bind=True, max_retries=2, queue=CeleryQueue.LONG_RUNNING.value, soft_time_limit=150, time_limit=180)
def build_canvas(self: Any, build_id: str, team_id: int) -> None:
    build = CanvasBuild.objects.for_team(team_id).select_related("source_version", "canvas").filter(id=build_id).first()
    if build is None or build.build_status in {CanvasBuild.Status.READY, CanvasBuild.Status.FAILED}:
        return
    started_at = timezone.now()
    claimed = (
        CanvasBuild.objects.for_team(team_id)
        .filter(id=build.id, build_status=CanvasBuild.Status.QUEUED)
        .update(build_status=CanvasBuild.Status.BUILDING, started_at=started_at)
    )
    if not claimed:
        claimed = (
            CanvasBuild.objects.for_team(team_id)
            .filter(
                id=build.id,
                build_status=CanvasBuild.Status.BUILDING,
                started_at__lt=started_at - timedelta(minutes=5),
            )
            .update(started_at=started_at)
        )
    if not claimed:
        return
    try:
        result = _run_builder(build.source_version.read_project())
        diagnostics = result.get("diagnostics")
        if result.get("ok") is not True:
            _fail_build(build, diagnostics if isinstance(diagnostics, list) else [])
            return
        artifacts, manifest = _validated_artifacts(result)
        _complete_build(build, artifacts, manifest)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as error:
        if self.request.retries < self.max_retries:
            CanvasBuild.objects.for_team(team_id).filter(id=build.id).update(build_status=CanvasBuild.Status.QUEUED)
            raise self.retry(exc=error, countdown=2 ** (self.request.retries + 1))
        _fail_build(
            build,
            [
                {
                    "severity": "error",
                    "code": "build_unavailable",
                    "message": "The canvas build service is unavailable. Retry the build.",
                }
            ],
        )
    except (RuntimeError, ValueError) as error:
        _fail_build(build, [{"severity": "error", "code": "invalid_build_output", "message": str(error)[:10_000]}])


def _older_than(metadata: dict[str, Any] | None, cutoff: Any) -> bool:
    if not metadata:
        return False
    modified = metadata.get("LastModified")
    return bool(modified and modified < cutoff)


@shared_task(queue=CeleryQueue.LONG_RUNNING.value, soft_time_limit=300, time_limit=360)
def collect_canvas_objects() -> None:
    now = timezone.now()
    protected_build_ids: set[Any] = set()
    for active_id, previous_id in CanvasApplication.objects.unscoped().values_list(
        "active_build_id", "previous_build_id"
    ):
        if active_id:
            protected_build_ids.add(active_id)
        if previous_id:
            protected_build_ids.add(previous_id)

    expired_builds = (
        CanvasBuild.objects.unscoped()
        .exclude(id__in=protected_build_ids)
        .exclude(pinned=True)
        .filter(
            completed_at__lt=now - timedelta(days=30),
            artifact_object_prefix__isnull=False,
        )
    )
    for build in expired_builds.iterator(chunk_size=100):
        keys = object_storage.list_objects(build.artifact_object_prefix or "") or []
        if keys:
            object_storage.delete_objects(keys)
        CanvasBuild.objects.unscoped().filter(id=build.id).update(artifact_object_prefix=None)

    source_keys = set(CanvasSourceVersion.objects.unscoped().values_list("source_object_key", flat=True))
    for key in object_storage.list_objects("canvas/source/") or []:
        if key not in source_keys and _older_than(object_storage.head_object(key), now - timedelta(days=1)):
            object_storage.delete(key)

    build_ids = {
        str(value)
        for value in CanvasBuild.objects.unscoped()
        .filter(artifact_object_prefix__isnull=False)
        .values_list("id", flat=True)
    }
    for key in object_storage.list_objects("canvas/artifacts/") or []:
        parts = key.split("/")
        if len(parts) < 5 or parts[3] in build_ids:
            continue
        if _older_than(object_storage.head_object(key), now - timedelta(days=1)):
            object_storage.delete(key)
