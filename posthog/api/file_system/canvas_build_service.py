"""Source-version and build lifecycle for canvases.

The relational rows (`CanvasSourceVersion`, `CanvasBuild`) are the control
plane; content lives in object storage:

- serialized source projects under a private, content-addressed key
  (``canvas_source/…``) — never served from the user-content origin;
- built artifact files under an immutable per-build prefix
  (``canvas_artifact/…``).

Publishing is upload-then-commit: the source object is uploaded before the
canvas row's transaction inserts the version/build rows and advances the
current-source pointer, so a conflicting transaction leaves at most an
unreferenced upload for the retention sweep — never a partially published
version. Deduplication is content-addressed but never crosses a canvas (a
shared object identity across tenants would leak that identical source
exists elsewhere).
"""

import gzip
import json
import time
import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.api.file_system.canvas_source import (
    CANVAS_COMPONENT_PATH,
    SYNTHETIC_INDEX_HTML,
    extract_legacy_code,
    has_errors,
    validate_source_project,
)
from posthog.models.file_system.canvas_build import CanvasBuild, CanvasSourceVersion
from posthog.models.file_system.file_system import FileSystem
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

# Retention policy (see the canvas build pipeline plan): every referenced
# source version is kept for the canvas's lifetime; artifacts are bounded.
FAILED_BUILD_RETENTION = timedelta(hours=24)
SUCCESSFUL_BUILD_RETENTION = timedelta(days=30)


def serialize_source_project(project: dict[str, Any]) -> tuple[bytes, str, int]:
    """Canonical serialization: (gzip payload, hex sha256 of the canonical JSON, size)."""
    canonical = json.dumps(project, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return gzip.compress(canonical, mtime=0), digest, len(canonical)


def source_object_key(team_id: int, canvas_id: str | UUID, source_hash: str) -> str:
    return f"canvas_source/team_{team_id}/{canvas_id}/{source_hash}.json.gz"


def artifact_object_prefix(team_id: int, canvas_id: str | UUID, build_id: str | UUID) -> str:
    return f"canvas_artifact/team_{team_id}/{canvas_id}/{build_id}"


def upload_source_project(team_id: int, canvas_id: str | UUID, project: dict[str, Any]) -> tuple[str, str, int]:
    """Upload the serialized project (idempotent — the key is content-addressed).

    Returns (object key, source hash, canonical size). Raises
    ObjectStorageError when storage is unavailable; callers decide whether the
    publish degrades to legacy-only or fails.
    """
    payload, digest, size = serialize_source_project(project)
    key = source_object_key(team_id, canvas_id, digest)
    object_storage.write(key, payload, extras={"ContentType": "application/gzip"})
    return key, digest, size


def read_source_project(version: CanvasSourceVersion) -> dict[str, Any]:
    payload = object_storage.read_bytes(version.source_object_key)
    if payload is None:
        raise object_storage.ObjectStorageError(f"source object {version.source_object_key} is missing")
    canonical = gzip.decompress(payload)
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != version.source_hash:
        raise object_storage.ObjectStorageError(
            f"source object {version.source_object_key} failed integrity verification"
        )
    return json.loads(canonical)


def record_publish(
    dashboard: FileSystem,
    meta: dict[str, Any],
    *,
    project: dict[str, Any],
    source_object: tuple[str, str, int],
    legacy_version_id: str,
    prompt: str | None,
    task_id: UUID | None,
    created_by_id: int | None,
) -> CanvasBuild:
    """Insert the source version + queued build inside the publish transaction.

    Must run while the canvas row is locked, after the legacy meta merge:
    mutates `meta` to advance `currentSourceVersionId` and enqueues the build
    worker on commit. The caller saves the row.
    """
    key, digest, size = source_object
    parent_id = meta.get("currentSourceVersionId")
    parent = CanvasSourceVersion.objects.for_team(dashboard.team_id).filter(id=parent_id).first() if parent_id else None
    version = CanvasSourceVersion.objects.create(
        team_id=dashboard.team_id,
        canvas=dashboard,
        parent_version=parent,
        source_hash=digest,
        source_object_key=key,
        source_size=size,
        task_id=task_id,
        prompt=prompt or None,
        legacy_version_id=legacy_version_id,
        created_by_id=created_by_id,
    )
    build = CanvasBuild.objects.create(
        team_id=dashboard.team_id,
        canvas=dashboard,
        source_version=version,
        status=CanvasBuild.STATUS_QUEUED,
    )
    meta["currentSourceVersionId"] = str(version.id)

    def enqueue() -> None:
        from posthog.tasks.canvas_build import process_canvas_build  # noqa: PLC0415 — avoids a task/api import cycle

        process_canvas_build.delay(dashboard.team_id, str(build.id))

    transaction.on_commit(enqueue)
    return build


def run_canvas_build(team_id: int, build_id: str) -> None:
    """The cloud build worker body.

    Validates the recorded source project, uploads the immutable artifact
    files, and marks the build ready — advancing the canvas's live pointer
    only if this build's source version is still the canvas's current head. A
    failed build records diagnostics and leaves the last-known-good build
    untouched. Idempotent: a re-delivered task for a finished build is a no-op.

    Until the isolated build image (node + esbuild, the shared build recipe)
    ships, the artifact for legacy-compatible projects freezes the project
    files themselves — the runtime keeps compiling the component exactly as it
    does today, now from an immutable, content-addressed snapshot.
    """
    build = CanvasBuild.objects.for_team(team_id).filter(id=build_id).select_related("source_version", "canvas").first()
    if build is None:
        logger.warning("canvas_build_missing", build_id=build_id)
        return
    if build.status not in (CanvasBuild.STATUS_QUEUED, CanvasBuild.STATUS_BUILDING):
        return

    build.status = CanvasBuild.STATUS_BUILDING
    build.save(update_fields=["status"])

    try:
        project = read_source_project(build.source_version)
    except object_storage.ObjectStorageError as error:
        _finish_failed(
            build,
            [
                {
                    "severity": "error",
                    "code": "source_unreadable",
                    "message": f"could not load the source project: {error}",
                }
            ],
        )
        return

    diagnostics = validate_source_project(project)
    if has_errors(diagnostics):
        _finish_failed(build, diagnostics)
        return

    prefix = artifact_object_prefix(build.team_id, build.canvas_id, build.id)
    entry_html = project.get("entryHtml", "index.html")
    files = dict(project["files"])
    # A legacy-compatible project may omit its entry shell (the read path
    # synthesizes it); the frozen artifact must be self-consistent, so
    # materialize the same shell the runtime would.
    files.setdefault(entry_html, SYNTHETIC_INDEX_HTML)
    assets = []
    for path, content in sorted(files.items()):
        content_bytes = content.encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        object_storage.write(f"{prefix}/{path}", content_bytes, extras={"ContentType": "text/plain; charset=utf-8"})
        assets.append({"path": path, "contentHash": content_hash, "sizeBytes": len(content_bytes)})

    manifest = {
        "entryHtml": entry_html,
        "assets": assets,
        "dependencies": project.get("dependencies", {}),
        "canvasSdkVersion": project.get("canvasSdkVersion", "0.1.0"),
        "capabilities": {
            "posthog": {"insights": [], "inlineQueries": True, "captureEvents": []},
            "network": {"origins": []},
        },
        # The legacy runtime mounts this component; the isolated build image
        # will replace this with compiled chunks under the same manifest shape.
        "legacyComponentPath": CANVAS_COMPONENT_PATH,
        "legacyCode": extract_legacy_code(project) if CANVAS_COMPONENT_PATH in project["files"] else None,
    }
    integrity = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    # Second transaction: mark ready and advance the live pointer only while
    # this build is still eligible (its source version is still the head).
    with transaction.atomic():
        dashboard = FileSystem.objects.select_for_update().get(pk=build.canvas_id)
        build.status = CanvasBuild.STATUS_READY
        build.artifact_object_prefix = prefix
        build.integrity = integrity
        build.manifest = manifest
        build.diagnostics = diagnostics
        build.finished_at = timezone.now()
        build.save(
            update_fields=["status", "artifact_object_prefix", "integrity", "manifest", "diagnostics", "finished_at"]
        )

        meta = dict(dashboard.meta or {})
        if meta.get("currentSourceVersionId") == str(build.source_version_id):
            meta["publishedBuildId"] = str(build.id)
            meta["updatedAt"] = int(time.time() * 1000)
            dashboard.meta = meta
            dashboard.save(update_fields=["meta"])


def _finish_failed(build: CanvasBuild, diagnostics: list[dict[str, Any]]) -> None:
    build.status = CanvasBuild.STATUS_FAILED
    build.diagnostics = diagnostics
    build.finished_at = timezone.now()
    build.save(update_fields=["status", "diagnostics", "finished_at"])


def cleanup_canvas_builds() -> int:
    """Apply the artifact retention policy; returns the number of builds pruned.

    Keeps, per canvas: the active (published) build, the most recent other
    successful build (instant rollback), and every pinned build. Other ready
    builds lose their artifacts after 30 days (they remain rebuildable from
    the retained source); failed builds lose theirs after 24 hours. Source
    versions are never pruned — history, undo, and rebuilds depend on them.
    """
    now = timezone.now()
    pruned = 0
    stale = (
        CanvasBuild.objects.unscoped()
        .filter(pinned=False, artifact_object_prefix__isnull=False)
        .filter(
            Q(status=CanvasBuild.STATUS_FAILED, finished_at__lt=now - FAILED_BUILD_RETENTION)
            | Q(status=CanvasBuild.STATUS_READY, finished_at__lt=now - SUCCESSFUL_BUILD_RETENTION)
        )
        .select_related("canvas")
        .order_by("canvas_id", "-created_at")
    )
    protected: dict[str, set[str]] = {}
    for build in stale:
        canvas_key = str(build.canvas_id)
        if canvas_key not in protected:
            meta = build.canvas.meta or {}
            keep = {meta.get("publishedBuildId")}
            rollback = (
                CanvasBuild.objects.unscoped()
                .filter(canvas_id=build.canvas_id, status=CanvasBuild.STATUS_READY)
                .exclude(id__in=[identifier for identifier in keep if identifier])
                .order_by("-created_at")
                .values_list("id", flat=True)
                .first()
            )
            keep.add(str(rollback) if rollback else None)
            protected[canvas_key] = {identifier for identifier in keep if identifier}
        if str(build.id) in protected[canvas_key]:
            continue

        assets = (build.manifest or {}).get("assets", [])
        keys = [f"{build.artifact_object_prefix}/{asset['path']}" for asset in assets]
        if keys:
            object_storage.delete_objects(keys)
        build.artifact_object_prefix = None
        build.save(update_fields=["artifact_object_prefix"])
        pruned += 1
    return pruned
