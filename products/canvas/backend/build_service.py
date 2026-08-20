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
import shutil
import hashlib
import subprocess
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from prometheus_client import Counter, Gauge, Histogram

from posthog.event_usage import groups
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.scoping import team_scope
from posthog.models.user import User
from posthog.ph_client import ph_background_capture
from posthog.storage import object_storage

from products.canvas.backend import error_reports
from products.canvas.backend.capabilities import CapabilityWidening, capability_widening
from products.canvas.backend.contract import CANVAS_BUILDER_DIR, contract_limits
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.source import (
    SYNTHETIC_INDEX_HTML,
    diagnostic,
    has_errors,
    synthetic_source_project,
    validate_relative_path,
    validate_source_project,
)
from products.tasks.backend.facade.sandbox import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxNotRunningError,
    SandboxProvisionError,
    SandboxTimeoutError,
)

logger = structlog.get_logger(__name__)

MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM = 20
MAX_PINNED_BUILDS_PER_CANVAS = 10
MAX_BUILD_ATTEMPTS = 3

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
CANVAS_BUILD_SWEEP_OUTCOMES = Counter(
    "posthog_canvas_build_sweep_total", "Stuck canvas builds handled by the sweeper", ["outcome"]
)
CANVAS_BUILD_ACTIVE = Gauge("posthog_canvas_builds_active", "Canvas builds currently queued or building")


CANVAS_BUILDER_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "NODE_ENV": "production"}


class CanvasBuildCapacityExceeded(Exception):
    """The team already has the maximum number of in-flight builds."""


class CanvasVersionConflict(Exception):
    """A guarded publish was based on a version that is no longer the head."""

    def __init__(self, current_version_id: str | None) -> None:
        super().__init__("The canvas changed since it was read.")
        self.current_version_id = current_version_id


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
    # node_modules is git-ignored (production bakes it into the sandbox image),
    # so a fresh checkout fails module resolution on the first import. Catch it
    # before spawning to name the fix instead of surfacing esbuild's stderr.
    if not (CANVAS_BUILDER_DIR / "node_modules").is_dir():
        raise RuntimeError(
            "canvas builder dependencies are not installed — run `npm ci` in products/canvas/packages/canvas_builder"
        )
    process = subprocess.run(
        [node_executable(), "--max-old-space-size=256", str(CANVAS_BUILDER_DIR / "build.mjs")],
        input=json.dumps({"project": project}, separators=(",", ":")),
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
        cwd=CANVAS_BUILDER_DIR,
        env=CANVAS_BUILDER_ENV,
    )
    if process.returncode != 0:
        raise RuntimeError(f"canvas builder exited with {process.returncode}: {(process.stderr or '')[-500:]}")
    result = json.loads(process.stdout)
    if not isinstance(result, dict):
        raise ValueError("canvas builder returned an invalid response")
    return result


def _run_sandbox_builder(project: dict[str, Any]) -> dict[str, Any]:
    from products.tasks.backend.facade.sandbox import (  # noqa: PLC0415 — sandbox provisioning is heavyweight; keep it off this module's import path
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
    # The builder script, its manifest, and node_modules are baked into the
    # CANVAS_BUILD image — only the project payload crosses into the sandbox.
    with get_sandbox_class().create(config) as sandbox:
        input_write = sandbox.write_file(
            "/tmp/canvas-build-input.json", json.dumps({"project": project}, separators=(",", ":")).encode()
        )
        if input_write.exit_code != 0:
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
    # Artifact paths carry builder-emitted names, so the source charset rule
    # does not apply — only structural safety.
    return validate_relative_path(value, restrict_charset=False) is None


def validate_builder_output(
    result: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    limits = contract_limits()
    if result.get("contractVersion") != 1 or result.get("status") != "ready":
        raise ValueError("canvas builder did not return a ready contract")
    files = result.get("files")
    manifest = result.get("manifest")
    diagnostics = result.get("diagnostics")
    if not isinstance(files, list) or not isinstance(manifest, dict) or not isinstance(diagnostics, list):
        raise ValueError("canvas builder omitted artifacts, manifest, or diagnostics")
    if len(files) > limits["maxArtifactFiles"]:
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
        if size > limits["maxArtifactFileBytes"]:
            raise ValueError("canvas artifact exceeds the per-file size limit")
        seen.add(path)
        emitted_metadata[path] = (digest, size)
        total += size
    if total > limits["maxArtifactTotalBytes"]:
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


# Retention policy: every referenced source version is kept for the canvas's
# lifetime; artifacts are bounded.
FAILED_BUILD_RETENTION = timedelta(hours=24)
SUCCESSFUL_BUILD_RETENTION = timedelta(days=30)
BUILD_LEASE_DURATION = timedelta(minutes=5)
# A queued build no worker has claimed after this long is presumed lost
# (dropped broker message) and re-delivered by the sweeper.
STALE_QUEUED_REDELIVERY_AFTER = timedelta(minutes=5)
# A queued build still unclaimed after this long is failed outright — the
# queue is not coming back for it, and it must not hold a capacity slot.
STALE_QUEUED_FAILURE_AFTER = timedelta(hours=6)


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
    ObjectStorageError when storage is unavailable — a publish cannot proceed
    without its source of record.
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


def current_source_project(canvas: Canvas) -> tuple[dict[str, Any], str | None]:
    """The canvas's head source project and version id.

    Reads the stored head version when one exists; a canvas that predates the
    relational lifecycle (or has never been published) is presented as a
    synthetic single-file project.
    """
    if canvas.current_source_version_id:
        version = CanvasSourceVersion.objects.for_team(canvas.team_id).get(pk=canvas.current_source_version_id)
        return read_source_project(version), str(version.id)
    return synthetic_source_project(canvas.legacy_code), None


def _lock_team_build_capacity(team_id: int) -> None:
    """Serialize team-wide capacity checks inside the current transaction.

    Publishes race on different canvas rows, so a row lock cannot guard the
    per-team cap — a transaction-scoped advisory lock can.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"canvas_build_cap:{team_id}"])


def _assert_build_capacity(team_id: int) -> None:
    active = CanvasBuild.objects.for_team(team_id).filter(status__in=CanvasBuild.ACTIVE_STATUSES).count()
    if active >= MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM:
        raise CanvasBuildCapacityExceeded


def _claim_canvas_head(
    canvas: Canvas,
    *,
    has_expected_version: bool,
    expected_version_id: str | UUID | None,
    check_capacity: bool = True,
) -> Canvas:
    """Lock the canvas row and claim the right to advance its head.

    Enforces the optimistic-version guard under the row lock, and (unless
    check_capacity is False) the team build-capacity cap under the team advisory
    lock. Promote passes check_capacity=False so adopting an already-built draft
    can't be blocked by the cap; it enforces capacity itself on the rebuild path.
    Must run inside a transaction; returns the locked row. Raises
    CanvasVersionConflict or CanvasBuildCapacityExceeded.
    """
    locked = Canvas.objects.for_team(canvas.team_id).select_for_update().get(pk=canvas.pk)
    current_id = str(locked.current_source_version_id) if locked.current_source_version_id else None
    expected = str(expected_version_id) if expected_version_id else None
    if has_expected_version and current_id != expected:
        raise CanvasVersionConflict(current_id)
    if check_capacity:
        _lock_team_build_capacity(locked.team_id)
        _assert_build_capacity(locked.team_id)
    return locked


def _queue_build(version: CanvasSourceVersion) -> CanvasBuild:
    """Create a queued build for the version and supersede older queued builds.

    Must run inside a transaction holding the canvas row lock and the team
    capacity advisory lock; enqueues the worker on commit.
    """
    build = CanvasBuild.objects.create(
        team_id=version.team_id,
        canvas_id=version.canvas_id,
        source_version=version,
        status=CanvasBuild.STATUS_QUEUED,
    )
    CanvasBuild.objects.for_team(version.team_id).filter(
        canvas_id=version.canvas_id, status=CanvasBuild.STATUS_QUEUED
    ).exclude(id=build.id).update(
        status=CanvasBuild.STATUS_FAILED,
        diagnostics=[
            diagnostic(
                "warning", "superseded", "A newer canvas source version was published before this build started."
            )
        ],
        finished_at=timezone.now(),
    )
    transaction.on_commit(lambda: _enqueue_build(build))
    return build


def _enqueue_build(build: CanvasBuild) -> None:
    """Hand the build to the worker queue and mark when that happened.

    Stamping ``enqueued_at`` is what lets the sweeper distinguish a build the
    broker lost (queue it again) from a build a worker was just told about —
    keyed off ``created_at`` instead, a retry of an old failed build would be
    re-delivered (a duplicate enqueue) every sweep until it was claimed.
    """
    from products.canvas.backend.tasks import process_canvas_build  # noqa: PLC0415 — avoids a task/service import cycle

    CanvasBuild.objects.unscoped().filter(id=build.id).update(enqueued_at=timezone.now())
    process_canvas_build.delay(build.team_id, str(build.id))


def publish_source_project(
    canvas: Canvas,
    *,
    project: dict[str, Any],
    prompt: str | None,
    name: str | None,
    has_expected_version: bool,
    expected_version_id: str | None,
    task_id: UUID | None,
    created_by: User | None,
    was_impersonated: bool = False,
) -> tuple[Canvas, CanvasSourceVersion, CanvasBuild, bool]:
    """Publish a validated project as the canvas's new head version.

    Upload-then-commit: the immutable source object goes up before the
    transaction, so a conflicting publish leaves at most an unreferenced
    upload. Writes the "published" activity-log entry here (not in the API
    layer) so every caller is audited and the capabilities diff is computed
    against the head this publish actually replaced. Returns (canvas,
    version, build, first_publish). Raises CanvasVersionConflict,
    CanvasBuildCapacityExceeded, or ObjectStorageError.
    """
    # Lock-free fail-fast: reject a doomed publish before paying for the
    # upload. Its answer can go stale before the commit transaction re-checks
    # authoritatively under locks, so taking them here would only double lock
    # contention per publish.
    with team_scope(canvas.team_id):
        current = Canvas.objects.for_team(canvas.team_id).only("current_source_version_id").get(pk=canvas.pk)
        current_id = str(current.current_source_version_id) if current.current_source_version_id else None
        expected = str(expected_version_id) if expected_version_id else None
        if has_expected_version and current_id != expected:
            raise CanvasVersionConflict(current_id)
        _assert_build_capacity(canvas.team_id)

    key, digest, size = upload_source_project(canvas.team_id, canvas.id, project)

    # A migrated canvas's pre-relational source must survive its first publish:
    # it becomes a real parent version here so history (undo/revert) can reach
    # it — otherwise nulling legacy_code below would discard the only copy.
    # Same upload-then-commit posture as the main project.
    legacy_upload: tuple[str, str, int] | None = None
    if current_id is None and (canvas.legacy_code or "").strip():
        legacy_upload = upload_source_project(canvas.team_id, canvas.id, synthetic_source_project(canvas.legacy_code))

    with transaction.atomic(), team_scope(canvas.team_id):
        canvas = _claim_canvas_head(
            canvas, has_expected_version=has_expected_version, expected_version_id=expected_version_id
        )
        first_publish = canvas.current_source_version_id is None and not (canvas.legacy_code or "").strip()
        if (
            legacy_upload is not None
            and canvas.current_source_version_id is None
            and (canvas.legacy_code or "").strip()
        ):
            legacy_key, legacy_digest, legacy_size = legacy_upload
            canvas.current_source_version = CanvasSourceVersion.objects.create(
                team_id=canvas.team_id,
                canvas=canvas,
                source_hash=legacy_digest,
                source_object_key=legacy_key,
                source_size=legacy_size,
                prompt="Imported source",
            )
        version = CanvasSourceVersion.objects.create(
            team_id=canvas.team_id,
            canvas=canvas,
            parent_version_id=canvas.current_source_version_id,
            source_hash=digest,
            source_object_key=key,
            source_size=size,
            task_id=task_id,
            prompt=prompt or None,
            created_by=created_by,
            capabilities=project.get("capabilities") or {},
            component_meta=project.get("component"),
        )
        build = _queue_build(version)

        canvas.current_source_version = version
        # A real version now exists; the pre-relational fallback is obsolete.
        canvas.legacy_code = None
        update_fields = ["current_source_version", "legacy_code", "updated_at"]
        if name and name.strip() and name.strip() != canvas.name:
            canvas.name = name.strip()
            update_fields.append("name")
        canvas.save(update_fields=update_fields)

    # The pre-publish capabilities come from the parent version the claim
    # recorded under the head lock, so the diff is exact even against a
    # concurrent publish.
    changes = _capabilities_changes(
        _version_capabilities(canvas.team_id, version.parent_version_id), version.capabilities
    )
    _log_canvas_activity(
        canvas,
        user=created_by,
        was_impersonated=was_impersonated,
        activity="published",
        detail=Detail(name=canvas.name, changes=changes),
    )

    return canvas, version, build, first_publish


def publish_grid_layout(
    canvas: Canvas,
    *,
    layout: dict[str, Any],
    prompt: str | None,
    has_expected_version: bool,
    expected_version_id: str | None,
    task_id: UUID | None,
    created_by: User | None,
    was_impersonated: bool = False,
) -> tuple[Canvas, CanvasSourceVersion]:
    """Publish a validated layout document as a grid canvas's new head version.

    Same upload-then-commit versioning as file projects, but no build is
    queued and no capacity is consumed: layout is data, so the new version is
    live the moment the head advances. Raises CanvasVersionConflict or
    ObjectStorageError.
    """
    # Lock-free fail-fast, mirroring the file-project publish: reject a stale
    # publish before paying for the upload, so a doomed patch does not leave an
    # orphaned, unreferenced source object behind. Conflicts are routine on this
    # path (an agent filling a box and a user dragging widgets guard against each
    # other), so this is the common case, not a rare race. The commit transaction
    # re-checks authoritatively under the head lock in _claim_canvas_head.
    if has_expected_version:
        with team_scope(canvas.team_id):
            current = Canvas.objects.for_team(canvas.team_id).only("current_source_version_id").get(pk=canvas.pk)
            current_id = str(current.current_source_version_id) if current.current_source_version_id else None
            expected = str(expected_version_id) if expected_version_id else None
            if current_id != expected:
                raise CanvasVersionConflict(current_id)
    key, digest, size = upload_source_project(canvas.team_id, canvas.id, layout)
    with transaction.atomic(), team_scope(canvas.team_id):
        canvas = _claim_canvas_head(
            canvas,
            has_expected_version=has_expected_version,
            expected_version_id=expected_version_id,
            check_capacity=False,
        )
        version = CanvasSourceVersion.objects.create(
            team_id=canvas.team_id,
            canvas=canvas,
            parent_version_id=canvas.current_source_version_id,
            source_hash=digest,
            source_object_key=key,
            source_size=size,
            task_id=task_id,
            prompt=prompt or None,
            created_by=created_by,
        )
        canvas.current_source_version = version
        canvas.save(update_fields=["current_source_version", "updated_at"])
    _log_canvas_activity(
        canvas,
        user=created_by,
        was_impersonated=was_impersonated,
        activity="published",
        detail=Detail(name=canvas.name),
    )
    return canvas, version


def publish_current_source_version(
    canvas: Canvas,
    expected_current_version_id: str | UUID,
    *,
    user: User | None = None,
    was_impersonated: bool = False,
) -> tuple[Canvas, CanvasBuild]:
    """Queue a build for the current source version without changing source or metadata."""
    with transaction.atomic(), team_scope(canvas.team_id):
        canvas = _claim_canvas_head(
            canvas,
            has_expected_version=True,
            expected_version_id=expected_current_version_id,
        )
        if canvas.current_source_version_id is None:
            raise CanvasVersionConflict(None)
        version = CanvasSourceVersion.objects.for_team(canvas.team_id).get(
            pk=canvas.current_source_version_id,
            canvas_id=canvas.id,
        )
        build = _queue_build(version)
    _log_canvas_activity(
        canvas,
        user=user,
        was_impersonated=was_impersonated,
        activity="published",
        detail=Detail(name=canvas.name),
    )
    return canvas, build


def revert_to_version(
    canvas: Canvas,
    version_id: str | UUID,
    expected_current_version_id: str | UUID | None,
    *,
    user: User | None = None,
    was_impersonated: bool = False,
) -> tuple[Canvas, CanvasBuild]:
    """Move the canvas's head back to an existing published version and rebuild it.

    Drafts are not revertable: a draft reaches the head only through
    promote_draft_version, which surfaces its capability widening first.
    Raises CanvasSourceVersion.DoesNotExist for a version that isn't one of this
    canvas's published versions, and CanvasBuildCapacityExceeded when the team
    cap is reached.
    """
    with transaction.atomic(), team_scope(canvas.team_id):
        canvas = _claim_canvas_head(canvas, has_expected_version=True, expected_version_id=expected_current_version_id)
        previous_head_id = str(canvas.current_source_version_id) if canvas.current_source_version_id else None
        version = CanvasSourceVersion.objects.for_team(canvas.team_id).get(
            pk=version_id, canvas_id=canvas.id, draft=False
        )
        canvas.current_source_version = version
        canvas.save(update_fields=["current_source_version", "updated_at"])
        build = _queue_build(version)
    _log_canvas_activity(
        canvas,
        user=user,
        was_impersonated=was_impersonated,
        activity="reverted",
        detail=Detail(
            name=canvas.name,
            changes=[
                Change(
                    type="Canvas",
                    action="changed",
                    field="current_source_version",
                    before=previous_head_id,
                    after=str(version.id),
                )
            ],
        ),
    )
    return canvas, build


def create_draft_version(
    canvas: Canvas,
    *,
    project: dict[str, Any],
    prompt: str | None,
    task_id: UUID | None,
    created_by: User | None,
    was_impersonated: bool = False,
) -> tuple[CanvasSourceVersion, CanvasBuild, CapabilityWidening]:
    """Stage a validated project as a draft version and build it, without moving the head.

    A draft is a regular `CanvasSourceVersion` (same storage, history, and build
    pipeline) that is not the canvas head, so `_finalize_ready` never advances the
    live pointer to its build. Promote it with `promote_draft_version`. No version
    guard applies: a draft conflicts with nothing because it publishes nothing.
    Returns the widening of the draft's declared capabilities over the current
    head's, so callers can surface manifest growth before anything ships. Raises
    CanvasBuildCapacityExceeded or ObjectStorageError.
    """
    # Lock-free fail-fast, mirroring publish: reject a doomed draft before
    # paying for the upload. The commit transaction re-checks authoritatively
    # under the locks in _claim_canvas_head.
    with team_scope(canvas.team_id):
        _assert_build_capacity(canvas.team_id)

    key, digest, size = upload_source_project(canvas.team_id, canvas.id, project)
    with transaction.atomic(), team_scope(canvas.team_id):
        canvas = _claim_canvas_head(canvas, has_expected_version=False, expected_version_id=None)
        version = CanvasSourceVersion.objects.create(
            team_id=canvas.team_id,
            canvas=canvas,
            draft=True,
            parent_version_id=canvas.current_source_version_id,
            source_hash=digest,
            source_object_key=key,
            source_size=size,
            task_id=task_id,
            prompt=prompt or None,
            created_by=created_by,
            capabilities=project.get("capabilities") or {},
            component_meta=project.get("component"),
        )
        build = _queue_build(version)

    head_capabilities = _version_capabilities(canvas.team_id, version.parent_version_id)
    _log_canvas_activity(
        canvas,
        user=created_by,
        was_impersonated=was_impersonated,
        activity="drafted",
        detail=Detail(name=canvas.name, changes=_capabilities_changes(head_capabilities, version.capabilities)),
    )
    return version, build, capability_widening(head_capabilities, version.capabilities)


def promote_draft_version(
    canvas: Canvas,
    version_id: str | UUID,
    expected_current_version_id: str | UUID | None,
    *,
    user: User | None = None,
    was_impersonated: bool = False,
) -> tuple[Canvas, CanvasBuild]:
    """Make a draft version the canvas head, adopting its build when one exists.

    A ready build whose artifacts have not been pruned by the retention sweep goes
    live directly with no rebuild. A build still in flight is adopted as-is — the
    version is the head by the time it finalizes, so _finalize_ready advances the
    live pointer; queuing another would double the work (and _queue_build only
    supersedes queued builds, not building ones). Only when no usable build exists
    (failed, or pruned) is a fresh one queued, which is why the capacity cap is
    only checked on that path. The version guard is required, like revert: a
    successful promote proves the caller saw the head it replaced. Raises
    CanvasSourceVersion.DoesNotExist for a version that isn't one of this canvas's
    drafts, CanvasVersionConflict, and CanvasBuildCapacityExceeded (rebuilds only).
    """
    with transaction.atomic(), team_scope(canvas.team_id):
        # Same head guard as revert; capacity is only enforced on the rebuild
        # path below, so adopting a surviving build can't hit the cap.
        canvas = _claim_canvas_head(
            canvas, has_expected_version=True, expected_version_id=expected_current_version_id, check_capacity=False
        )
        previous_head_id = canvas.current_source_version_id
        version = CanvasSourceVersion.objects.for_team(canvas.team_id).get(
            pk=version_id, canvas_id=canvas.id, draft=True
        )
        version.draft = False
        version.save(update_fields=["draft"])
        canvas.current_source_version = version
        update_fields = ["current_source_version", "updated_at"]
        build = (
            version.builds.filter(status=CanvasBuild.STATUS_READY, artifact_object_prefix__isnull=False)
            .order_by("-created_at")
            .first()
        )
        if build is not None:
            canvas.published_build = build
            update_fields.append("published_build")
        else:
            build = version.builds.filter(status__in=CanvasBuild.ACTIVE_STATUSES).order_by("-created_at").first()
            if build is None:
                _lock_team_build_capacity(canvas.team_id)
                _assert_build_capacity(canvas.team_id)
                build = _queue_build(version)
        canvas.save(update_fields=update_fields)

    changes = _capabilities_changes(_version_capabilities(canvas.team_id, previous_head_id), version.capabilities)
    _log_canvas_activity(
        canvas,
        user=user,
        was_impersonated=was_impersonated,
        activity="published",
        detail=Detail(name=canvas.name, changes=changes),
    )
    return canvas, build


def _version_capabilities(team_id: int, version_id: str | UUID | None) -> dict | None:
    """The declared capabilities of a source version, or None when there is no such
    version. None means "predates the capabilities snapshot", not an empty manifest."""
    if not version_id:
        return None
    return (
        CanvasSourceVersion.objects.for_team(team_id)
        .filter(pk=version_id)
        .values_list("capabilities", flat=True)
        .first()
    )


def _capabilities_changes(before: dict | None, after: dict | None) -> list[Change] | None:
    """A one-field Change list recording a capabilities-manifest diff, or None when unchanged."""
    if before == after:
        return None
    return [Change(type="Canvas", action="changed", field="capabilities", before=before, after=after)]


def _log_canvas_activity(
    canvas: Canvas, *, user: User | None, was_impersonated: bool, activity: str, detail: Detail
) -> None:
    log_activity(
        organization_id=canvas.team.organization_id,
        team_id=canvas.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=canvas.id,
        scope="Canvas",
        activity=activity,
        detail=detail,
    )


def act_on_build(canvas: Canvas, build_id: str | UUID, action: str) -> CanvasBuild:
    """Apply a lifecycle action (retry, pin, unpin, cancel) to one build.

    Raises CanvasBuild.DoesNotExist for a build that isn't this canvas's,
    ValueError for an action the build's state doesn't allow, and
    CanvasBuildCapacityExceeded when a retry would exceed the team cap.
    """
    now = timezone.now()
    with transaction.atomic(), team_scope(canvas.team_id):
        Canvas.objects.for_team(canvas.team_id).select_for_update().get(pk=canvas.pk)
        build = CanvasBuild.objects.for_team(canvas.team_id).select_for_update().get(pk=build_id, canvas_id=canvas.id)
        if action == "pin":
            pinned_count = CanvasBuild.objects.for_team(canvas.team_id).filter(canvas_id=canvas.id, pinned=True).count()
            if not build.pinned and pinned_count >= MAX_PINNED_BUILDS_PER_CANVAS:
                raise ValueError(f"A canvas can retain at most {MAX_PINNED_BUILDS_PER_CANVAS} pinned builds.")
            build.pinned = True
            build.save(update_fields=["pinned"])
        elif action == "unpin":
            build.pinned = False
            build.save(update_fields=["pinned"])
        elif action == "retry":
            if build.status != CanvasBuild.STATUS_FAILED:
                raise ValueError("Only failed builds can be retried.")
            _lock_team_build_capacity(canvas.team_id)
            _assert_build_capacity(canvas.team_id)
            build.status = CanvasBuild.STATUS_QUEUED
            build.diagnostics = []
            build.finished_at = None
            build.lease_expires_at = None
            build.save(update_fields=["status", "diagnostics", "finished_at", "lease_expires_at"])
            transaction.on_commit(lambda: _enqueue_build(build))
        elif action == "cancel":
            lease_lapsed = build.lease_expires_at is not None and build.lease_expires_at < now
            if build.status != CanvasBuild.STATUS_QUEUED and not (
                build.status == CanvasBuild.STATUS_BUILDING and lease_lapsed
            ):
                raise ValueError("Only queued (or lease-expired) builds can be cancelled.")
            _finish_failed(build, [diagnostic("warning", "cancelled", "The build was cancelled.")])
            build.refresh_from_db()
        else:
            raise ValueError(f"Unknown build action: {action}")
    return build


def run_canvas_build(team_id: int, build_id: str) -> None:
    """The cloud build worker body.

    Validates the recorded source project, uploads the immutable artifact
    files, and marks the build ready — advancing the canvas's live pointer
    only if this build's source version is still the canvas's current head. A
    failed build records diagnostics and leaves the last-known-good build
    untouched. Idempotent: a re-delivered task for a finished build is a no-op.
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
        if build.status not in CanvasBuild.ACTIVE_STATUSES:
            return
        now = timezone.now()
        if build.status == CanvasBuild.STATUS_BUILDING and build.lease_expires_at and build.lease_expires_at > now:
            return
        build.status = CanvasBuild.STATUS_BUILDING
        build.attempt_count += 1
        build.lease_expires_at = now + BUILD_LEASE_DURATION
        build.save(update_fields=["status", "attempt_count", "lease_expires_at"])
        CANVAS_BUILD_QUEUE_SECONDS.observe(max(0, (now - build.enqueued_at).total_seconds()))

    try:
        project = read_source_project(build.source_version)
    except object_storage.ObjectStorageError:
        _requeue_or_fail(
            build,
            code="source_unreadable",
            message="could not load the source project: source storage remained unavailable after retries",
        )
        return

    diagnostics = validate_source_project(project, kind=build.canvas.kind)
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
    except (
        subprocess.TimeoutExpired,
        OSError,
        json.JSONDecodeError,
        RuntimeError,
        ValueError,
        SandboxCleanupError,
        SandboxExecutionError,
        SandboxNotFoundError,
        SandboxNotRunningError,
        SandboxProvisionError,
        SandboxTimeoutError,
    ) as error:
        logger.warning(
            "canvas_build_process_failed",
            build_id=str(build.id),
            error_type=type(error).__name__,
            error=str(error)[:500],
        )
        message = "The canvas build service is unavailable."
        if settings.DEBUG:
            # Local dev: keep the cause in the diagnostic the toolbar/agent
            # surfaces — the worker-log warning above is easy to miss, and the
            # usual causes (node off PATH, builder deps not installed) are
            # actionable. Production stays generic: sandbox stderr is internal.
            message = f"{message} {type(error).__name__}: {str(error)[:300]}"
        _finish_failed(build, [diagnostic("error", "build_unavailable", message)])
        return

    prefix = artifact_object_prefix(build.team_id, build.canvas_id, build.id)
    manifest_assets = {asset["path"]: asset for asset in manifest["assets"]}
    uploaded_keys: list[str] = []
    # Renew the lease as the upload runs so a slow object store can't let the
    # sweeper reclaim (and re-drive) a healthy in-flight build. The claim sets
    # lease_expires_at = claimed_at + BUILD_LEASE_DURATION; renew in increments
    # per file, keyed off wall-clock so writes stay cheap on small builds.
    lease_renew_after = BUILD_LEASE_DURATION / 2
    last_lease_touch = timezone.now()
    try:
        for artifact in files:
            now = timezone.now()
            if now - last_lease_touch >= lease_renew_after:
                CanvasBuild.objects.for_team(build.team_id).filter(id=build.id).update(
                    lease_expires_at=now + BUILD_LEASE_DURATION
                )
                last_lease_touch = now
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
            try:
                object_storage.delete_objects(uploaded_keys)
            except object_storage.ObjectStorageError:
                logger.warning("canvas_artifact_cleanup_failed", build_id=str(build.id))
        _requeue_or_fail(build, code="artifact_upload_failed", message="Artifact storage is unavailable.")
        return
    integrity = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    if not _finalize_ready(
        build,
        prefix=prefix,
        integrity=integrity,
        manifest=manifest,
        diagnostics=diagnostics,
    ):
        object_storage.delete_objects(uploaded_keys)
        CANVAS_BUILD_OUTCOMES.labels(outcome="failed", code="superseded_during_build").inc()
        return
    CANVAS_BUILD_OUTCOMES.labels(outcome="ready", code="").inc()
    CANVAS_BUILD_DURATION_SECONDS.labels(outcome="ready").observe(
        max(0, ((build.finished_at or timezone.now()) - build.created_at).total_seconds())
    )
    CANVAS_BUILD_ARTIFACT_BYTES.observe(sum(asset["sizeBytes"] for asset in manifest["assets"]))
    _capture_build_completed(build, outcome="ready")


def _capture_build_completed(build: CanvasBuild, *, outcome: str) -> None:
    """Product-analytics record of a terminal build, attributed to the version's
    publisher when there is one. Diagnostics contribute codes only — messages can
    quote source. Deferred to commit so no network work runs while a caller's
    transaction still holds row locks, and delivered through the background
    client (no per-call setup or blocking flush). Telemetry must never fail a
    build, so errors are swallowed.
    """

    def send() -> None:
        try:
            team = build.team
            user = build.source_version.created_by
            duration_seconds = max(0, ((build.finished_at or timezone.now()) - build.created_at).total_seconds())
            error_codes = [
                str(item.get("code"))
                for item in (build.diagnostics or [])
                if isinstance(item, dict) and item.get("severity") == "error"
            ][:10]
            ph_background_capture()(
                distinct_id=user.distinct_id if user else str(team.uuid),
                event="canvas build completed",
                properties={
                    "canvas_id": str(build.canvas_id),
                    "build_id": str(build.id),
                    "source_version_id": str(build.source_version_id),
                    "outcome": outcome,
                    "attempt_count": build.attempt_count,
                    "duration_seconds": round(duration_seconds, 2),
                    "error_codes": error_codes,
                },
                groups=groups(team.organization, team),
            )
        except Exception:
            logger.warning("canvas_build_capture_failed", build_id=str(build.id), exc_info=True)

    transaction.on_commit(send)


def _finalize_ready(
    stale_build: CanvasBuild,
    *,
    prefix: str,
    integrity: str,
    manifest: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> bool:
    """Mark a build READY and advance the canvas's live pointer, or bail.

    The claim lock from the first transaction is released for the whole
    build/upload phase, so this re-claims the row and re-checks the build is
    still in flight before writing — otherwise a cancel (or the sweeper failing
    the build) that landed mid-build would be clobbered back to READY by the
    stale in-memory row. Returns False when the build was finalized by someone
    else first. The live pointer only advances while this build's source
    version is still the canvas's head.
    """
    with transaction.atomic():
        # Lock canvas before build (same order as publish/revert) to avoid a
        # lock-ordering deadlock with a concurrent publish of the same canvas.
        canvas = Canvas.objects.for_team(stale_build.team_id).select_for_update().get(pk=stale_build.canvas_id)
        build = CanvasBuild.objects.for_team(stale_build.team_id).select_for_update().filter(id=stale_build.id).first()
        if build is None or build.status != CanvasBuild.STATUS_BUILDING:
            return False
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
        if canvas.current_source_version_id == build.source_version_id:
            canvas.published_build = build
            canvas.save(update_fields=["published_build", "updated_at"])
        # Mirror the outcome onto the caller's object for the duration metric.
        stale_build.status = build.status
        stale_build.finished_at = build.finished_at
    return True


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


def _requeue_or_fail(build: CanvasBuild, *, code: str, message: str) -> None:
    """Recover from a storage outage mid-build.

    While attempts remain, flips the row back to QUEUED and re-raises the
    ObjectStorageError being handled (the caller must invoke this from its
    except block); once attempts are exhausted, fails the build with one
    error diagnostic.
    """
    if build.attempt_count < MAX_BUILD_ATTEMPTS:
        CanvasBuild.objects.for_team(build.team_id).filter(id=build.id).update(
            status=CanvasBuild.STATUS_QUEUED, lease_expires_at=None
        )
        raise  # noqa: PLE0704 — re-raises the caller's in-flight ObjectStorageError
    _finish_failed(build, [diagnostic("error", code, message)])


def _finish_failed(stale_build: CanvasBuild, diagnostics: list[dict[str, Any]]) -> None:
    with transaction.atomic():
        build = (
            CanvasBuild.objects.for_team(stale_build.team_id)
            .select_for_update()
            .filter(id=stale_build.id, status__in=CanvasBuild.ACTIVE_STATUSES)
            .first()
        )
        if build is None:
            return
        build.status = CanvasBuild.STATUS_FAILED
        build.diagnostics = diagnostics
        build.finished_at = timezone.now()
        build.lease_expires_at = None
        build.save(update_fields=["status", "diagnostics", "finished_at", "lease_expires_at"])
    logger.warning(
        "canvas_build_failed",
        build_id=str(build.id),
        codes=[diagnostic.get("code") for diagnostic in diagnostics][:20],
    )
    code = str(diagnostics[0].get("code", "unknown")) if diagnostics else "unknown"
    CANVAS_BUILD_OUTCOMES.labels(outcome="failed", code=code).inc()
    CANVAS_BUILD_DURATION_SECONDS.labels(outcome="failed").observe(
        max(0, (build.finished_at - build.created_at).total_seconds())
    )
    _capture_build_completed(build, outcome="failed")
    error_reports.report_build_failure(build)


def sweep_canvas_builds() -> dict[str, int]:
    """Recover builds stuck in flight; returns per-outcome counts.

    Two ways a build wedges without ever reaching a terminal state, each
    permanently occupying one of the team's capacity slots:

    - the worker died mid-build (OOM, deploy) — its lease lapses and nothing
      re-drives the row;
    - the broker dropped the enqueue message — the row stays ``queued`` and no
      worker ever claims it.

    Lease-lapsed builds are requeued while attempts remain, else failed.
    Unclaimed queued builds are re-delivered, and failed outright once
    they're old enough that the queue clearly isn't coming back for them.
    """
    now = timezone.now()
    counts = {"requeued": 0, "failed": 0, "redelivered": 0}

    with transaction.atomic():
        expired = (
            CanvasBuild.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(status=CanvasBuild.STATUS_BUILDING, lease_expires_at__lt=now)[:200]
        )
        for build in expired:
            if build.attempt_count >= MAX_BUILD_ATTEMPTS:
                _finish_failed(
                    build,
                    [
                        diagnostic(
                            "error",
                            "build_lease_expired",
                            "The build worker stopped responding and the build ran out of attempts.",
                        )
                    ],
                )
                counts["failed"] += 1
            else:
                build.status = CanvasBuild.STATUS_QUEUED
                build.lease_expires_at = None
                build.save(update_fields=["status", "lease_expires_at"])
                transaction.on_commit(partial(_enqueue_build, build))
                counts["requeued"] += 1

    with transaction.atomic():
        # Staleness is measured off enqueued_at (when the build was last handed
        # to the queue), not created_at: a retried build is old but freshly
        # enqueued, and created_at would make the sweeper re-deliver it forever.
        stale_queued = (
            CanvasBuild.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(status=CanvasBuild.STATUS_QUEUED, enqueued_at__lt=now - STALE_QUEUED_REDELIVERY_AFTER)[:200]
        )
        for build in stale_queued:
            if build.enqueued_at < now - STALE_QUEUED_FAILURE_AFTER:
                _finish_failed(
                    build,
                    [diagnostic("error", "build_stuck", "The build was never picked up by a worker.")],
                )
                counts["failed"] += 1
            else:
                # Re-delivery is idempotent: the worker claims rows under a
                # row lock and no-ops on anything already claimed or finished.
                transaction.on_commit(partial(_enqueue_build, build))
                counts["redelivered"] += 1

    for outcome, count in counts.items():
        if count:
            CANVAS_BUILD_SWEEP_OUTCOMES.labels(outcome=outcome).inc(count)
    CANVAS_BUILD_ACTIVE.set(CanvasBuild.objects.unscoped().filter(status__in=CanvasBuild.ACTIVE_STATUSES).count())
    return counts


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
    pending_keys: list[str] = []
    pending_build_ids: list[UUID] = []

    def flush() -> None:
        # Clear prefixes only after their batch's delete succeeds — a storage
        # failure must leave the rows pointing at their (surviving) artifacts.
        nonlocal pruned
        if pending_keys:
            object_storage.delete_objects(pending_keys)
        if pending_build_ids:
            # nosemgrep: idor-lookup-without-team (cross-team retention sweep; ids collected from DB rows above, no user input)
            CanvasBuild.objects.unscoped().filter(id__in=pending_build_ids).update(artifact_object_prefix=None)
        pruned += len(pending_build_ids)
        pending_keys.clear()
        pending_build_ids.clear()

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
    for build in stale.iterator(chunk_size=500):
        canvas_key = str(build.canvas_id)
        if canvas_key not in protected:
            keep = {str(build.canvas.published_build_id) if build.canvas.published_build_id else None}
            rollback = (
                CanvasBuild.objects.unscoped()
                .filter(
                    canvas_id=build.canvas_id,
                    status=CanvasBuild.STATUS_READY,
                    artifact_object_prefix__isnull=False,
                )
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
        pending_keys.extend(f"{build.artifact_object_prefix}/{asset['path']}" for asset in assets)
        pending_build_ids.append(build.id)
        if len(pending_keys) >= 1000:
            flush()
    flush()
    return pruned
