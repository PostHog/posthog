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
import shutil
import hashlib
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from prometheus_client import Counter, Histogram

from posthog.api.file_system.canvas_source import SYNTHETIC_INDEX_HTML, has_errors, validate_source_project
from posthog.models.file_system.canvas_build import CanvasBuild, CanvasSourceVersion
from posthog.models.file_system.file_system import FileSystem
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

CANVAS_BUILDER_PATH = Path(__file__).resolve().parents[3] / "common" / "canvas-builder" / "build.mjs"
MAX_ARTIFACT_FILES = 256
MAX_ARTIFACT_FILE_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 12 * 1024 * 1024
MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM = 20

CANVAS_BUILD_OUTCOMES = Counter(
    "posthog_canvas_build_outcomes_total", "Canvas build terminal outcomes", ["outcome", "code"]
)
CANVAS_BUILD_QUEUE_SECONDS = Histogram(
    "posthog_canvas_build_queue_seconds", "Time a canvas build waits before execution"
)
CANVAS_BUILD_DURATION_SECONDS = Histogram(
    "posthog_canvas_build_duration_seconds", "End-to-end canvas build latency", ["outcome"]
)
CANVAS_BUILD_ARTIFACT_BYTES = Histogram(
    "posthog_canvas_build_artifact_bytes", "Total emitted bytes for successful canvas builds"
)


CANVAS_BUILDER_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "NODE_ENV": "production"}


def node_executable() -> str:
    """Resolve node against the worker's own PATH.

    The builder child gets a sanitized env so it never inherits credentials,
    which also means it cannot resolve `node` itself — outside the production
    image (flox, homebrew, CI toolcaches) node lives nowhere near that minimal
    PATH, so the interpreter has to be resolved here and passed absolute.
    """
    resolved = shutil.which("node") or shutil.which("node", path=CANVAS_BUILDER_ENV["PATH"])
    if resolved is None:
        raise RuntimeError("node is not on the canvas builder's PATH")
    return resolved


def _run_local_builder(project: dict[str, Any]) -> dict[str, Any]:
    process = subprocess.run(
        [node_executable(), "--max-old-space-size=256", str(CANVAS_BUILDER_PATH)],
        input=json.dumps({"project": project}, separators=(",", ":")),
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
        cwd=CANVAS_BUILDER_PATH.parent,
        env=CANVAS_BUILDER_ENV,
    )
    if process.returncode != 0:
        raise RuntimeError(f"canvas builder exited with {process.returncode}: {(process.stderr or '')[-500:]}")
    result = json.loads(process.stdout)
    if not isinstance(result, dict):
        raise ValueError("canvas builder returned an invalid response")
    return result


def _run_sandbox_builder(project: dict[str, Any]) -> dict[str, Any]:
    from products.tasks.backend.logic.services.sandbox import (  # noqa: PLC0415
        SandboxConfig,
        SandboxTemplate,
        get_sandbox_class,
    )

    config = SandboxConfig(
        name="canvas-build",
        template=SandboxTemplate.CANVAS_BUILD,
        default_execution_timeout_seconds=45,
        ttl_seconds=90,
        memory_gb=0.5,
        cpu_cores=1,
        disk_size_gb=1,
        block_network=True,
        environment_variables=None,
        metadata={"workload": "canvas-build"},
    )
    with get_sandbox_class().create(config) as sandbox:
        setup = sandbox.execute("mkdir -p /scripts/canvas-builder", timeout_seconds=10)
        if setup.exit_code != 0:
            raise RuntimeError(f"canvas sandbox setup failed: {setup.stderr[-500:]}")
        script_write = sandbox.write_file("/scripts/canvas-builder/build.mjs", CANVAS_BUILDER_PATH.read_bytes())
        input_write = sandbox.write_file(
            "/tmp/canvas-build-input.json", json.dumps({"project": project}, separators=(",", ":")).encode()
        )
        if script_write.exit_code != 0 or input_write.exit_code != 0:
            raise RuntimeError("canvas sandbox input upload failed")
        process = sandbox.execute(
            "node --max-old-space-size=256 /scripts/canvas-builder/build.mjs < /tmp/canvas-build-input.json",
            timeout_seconds=45,
        )
        if process.exit_code != 0:
            raise RuntimeError(f"canvas sandbox builder exited with {process.exit_code}: {process.stderr[-500:]}")
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise ValueError("canvas sandbox builder returned an invalid response")
        return result


def run_cloud_builder(project: dict[str, Any]) -> dict[str, Any]:
    if settings.DEBUG or settings.TEST:
        return _run_local_builder(project)
    return _run_sandbox_builder(project)


def _valid_artifact_path(value: str) -> bool:
    segments = value.split("/")
    return (
        bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and all(segment not in {"", ".", ".."} for segment in segments)
        and not any(character in value for character in "\r\n\0")
    )


def validate_builder_output(
    result: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if result.get("contractVersion") != 1 or result.get("status") != "ready":
        raise ValueError("canvas builder did not return a ready contract")
    files = result.get("files")
    manifest = result.get("manifest")
    diagnostics = result.get("diagnostics")
    if not isinstance(files, list) or not isinstance(manifest, dict) or not isinstance(diagnostics, list):
        raise ValueError("canvas builder omitted artifacts, manifest, or diagnostics")
    if len(files) > MAX_ARTIFACT_FILES:
        raise ValueError("canvas artifact manifest has too many files")
    seen: set[str] = set()
    emitted_metadata: dict[str, tuple[str, int]] = {}
    total = 0
    for artifact in files:
        if not isinstance(artifact, dict):
            raise ValueError("canvas builder emitted an invalid artifact")
        path = artifact.get("path")
        content = artifact.get("content")
        digest = artifact.get("contentHash")
        size = artifact.get("sizeBytes")
        if (
            not isinstance(path, str)
            or not _valid_artifact_path(path)
            or path in seen
            or not isinstance(content, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(size, int)
            or isinstance(size, bool)
        ):
            raise ValueError("canvas builder emitted an invalid artifact")
        encoded = content.encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != digest or len(encoded) != size:
            raise ValueError("canvas artifact integrity does not match its manifest")
        if size > MAX_ARTIFACT_FILE_BYTES:
            raise ValueError("canvas artifact exceeds the per-file size limit")
        seen.add(path)
        emitted_metadata[path] = (digest, size)
        total += size
    if total > MAX_ARTIFACT_TOTAL_BYTES:
        raise ValueError("canvas build exceeds the total artifact size limit")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or {asset.get("path") for asset in assets if isinstance(asset, dict)} != seen:
        raise ValueError("canvas artifact manifest does not match emitted files")
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("canvas artifact manifest metadata is invalid")
        path = asset.get("path")
        if not isinstance(path, str) or emitted_metadata.get(path) != (
            asset.get("contentHash"),
            asset.get("sizeBytes"),
        ):
            raise ValueError("canvas artifact manifest metadata does not match emitted files")
    entry = manifest.get("entryHtml")
    if not isinstance(entry, str) or entry not in seen:
        raise ValueError("canvas build does not contain its entry HTML")
    return files, manifest, diagnostics[:500]


# Retention policy (see the canvas build pipeline plan): every referenced
# source version is kept for the canvas's lifetime; artifacts are bounded.
FAILED_BUILD_RETENTION = timedelta(hours=24)
SUCCESSFUL_BUILD_RETENTION = timedelta(days=30)
BUILD_LEASE_DURATION = timedelta(minutes=5)


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
    CanvasBuild.objects.for_team(dashboard.team_id).filter(canvas=dashboard, status=CanvasBuild.STATUS_QUEUED).exclude(
        id=build.id
    ).update(
        status=CanvasBuild.STATUS_FAILED,
        diagnostics=[
            {
                "severity": "warning",
                "code": "superseded",
                "message": "A newer canvas source version was published before this build started.",
            }
        ],
        finished_at=timezone.now(),
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

    The isolated Node process runs the same versioned contract as local
    previews. Only its validated manifest and files may cross back into the
    control plane.
    """
    with transaction.atomic():
        build = (
            CanvasBuild.objects.for_team(team_id)
            .select_for_update()
            .filter(id=build_id)
            .select_related("source_version", "canvas")
            .first()
        )
        if build is None:
            logger.warning("canvas_build_missing", build_id=build_id)
            return
        if build.status not in (CanvasBuild.STATUS_QUEUED, CanvasBuild.STATUS_BUILDING):
            return
        now = timezone.now()
        if build.status == CanvasBuild.STATUS_BUILDING and build.lease_expires_at and build.lease_expires_at > now:
            return
        build.status = CanvasBuild.STATUS_BUILDING
        build.attempt_count += 1
        build.lease_expires_at = now + BUILD_LEASE_DURATION
        build.save(update_fields=["status", "attempt_count", "lease_expires_at"])
        CANVAS_BUILD_QUEUE_SECONDS.observe(max(0, (now - build.created_at).total_seconds()))

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

    project_files = dict(project["files"])
    project_files.setdefault(project.get("entryHtml", "index.html"), SYNTHETIC_INDEX_HTML)
    project = {**project, "files": project_files}
    try:
        result = run_cloud_builder(project)
        if result.get("status") != "ready":
            builder_diagnostics = result.get("diagnostics")
            _finish_failed(build, builder_diagnostics[:500] if isinstance(builder_diagnostics, list) else [])
            return
        files, manifest, diagnostics = validate_builder_output(result)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, RuntimeError, ValueError) as error:
        logger.warning(
            "canvas_build_process_failed",
            build_id=str(build.id),
            error_type=type(error).__name__,
            error=str(error)[:500],
        )
        _finish_failed(
            build,
            [{"severity": "error", "code": "build_unavailable", "message": "The canvas build service is unavailable."}],
        )
        return

    prefix = artifact_object_prefix(build.team_id, build.canvas_id, build.id)
    manifest_assets = {asset["path"]: asset for asset in manifest["assets"]}
    uploaded_keys: list[str] = []
    try:
        for artifact in files:
            content_type = _artifact_content_type(artifact["path"])
            key = f"{prefix}/{artifact['path']}"
            object_storage.write(
                key,
                artifact["content"].encode("utf-8"),
                extras={"ContentType": content_type, "CacheControl": "private, max-age=31536000, immutable"},
            )
            uploaded_keys.append(key)
            manifest_assets[artifact["path"]]["contentType"] = content_type
    except object_storage.ObjectStorageError:
        if uploaded_keys:
            object_storage.delete_objects(uploaded_keys)
        _finish_failed(
            build,
            [{"severity": "error", "code": "artifact_upload_failed", "message": "Artifact storage is unavailable."}],
        )
        return
    integrity = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    # Second transaction: mark ready and advance the live pointer only while
    # this build is still eligible (its source version is still the head).
    with transaction.atomic():
        dashboard = FileSystem.objects.select_for_update().get(pk=build.canvas_id, team_id=team_id)
        build.status = CanvasBuild.STATUS_READY
        build.artifact_object_prefix = prefix
        build.integrity = integrity
        build.manifest = manifest
        build.diagnostics = diagnostics
        build.finished_at = timezone.now()
        build.lease_expires_at = None
        build.save(
            update_fields=[
                "status",
                "artifact_object_prefix",
                "integrity",
                "manifest",
                "diagnostics",
                "finished_at",
                "lease_expires_at",
            ]
        )

        meta = dict(dashboard.meta or {})
        if meta.get("currentSourceVersionId") == str(build.source_version_id):
            meta["publishedBuildId"] = str(build.id)
            meta["updatedAt"] = int(time.time() * 1000)
            dashboard.meta = meta
            dashboard.save(update_fields=["meta"])
    CANVAS_BUILD_OUTCOMES.labels(outcome="ready", code="").inc()
    CANVAS_BUILD_DURATION_SECONDS.labels(outcome="ready").observe(
        max(0, (build.finished_at - build.created_at).total_seconds())
    )
    CANVAS_BUILD_ARTIFACT_BYTES.observe(sum(asset["sizeBytes"] for asset in manifest["assets"]))


def _artifact_content_type(path: str) -> str:
    if path.endswith(".html"):
        return "text/html; charset=utf-8"
    if path.endswith(".js"):
        return "text/javascript; charset=utf-8"
    if path.endswith(".css"):
        return "text/css; charset=utf-8"
    if path.endswith(".json"):
        return "application/json; charset=utf-8"
    return "application/octet-stream"


def _finish_failed(build: CanvasBuild, diagnostics: list[dict[str, Any]]) -> None:
    logger.warning(
        "canvas_build_failed",
        build_id=str(build.id),
        codes=[diagnostic.get("code") for diagnostic in diagnostics][:20],
    )
    build.status = CanvasBuild.STATUS_FAILED
    build.diagnostics = diagnostics
    build.finished_at = timezone.now()
    build.lease_expires_at = None
    build.save(update_fields=["status", "diagnostics", "finished_at", "lease_expires_at"])
    code = str(diagnostics[0].get("code", "unknown")) if diagnostics else "unknown"
    CANVAS_BUILD_OUTCOMES.labels(outcome="failed", code=code).inc()
    CANVAS_BUILD_DURATION_SECONDS.labels(outcome="failed").observe(
        max(0, (build.finished_at - build.created_at).total_seconds())
    )


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
