from django.db import models
from django.utils import timezone

from posthog.models.file_system.file_system import FileSystem
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class CanvasSourceVersion(TeamScopedRootMixin, UUIDModel):
    """One immutable published source project of a canvas.

    The project content itself lives in object storage (private, content
    addressed); this row is the control-plane record: pointers, hashes,
    attribution, and lineage. Rows are append-only — a publish never rewrites
    an existing version. The canvas's live pointer (`currentSourceVersionId`)
    stays in the desktop file-system row's meta during the migration; these
    tables own the normalized lifecycle.
    """

    # db_constraint=False: a real FK constraint to the hot posthog_team table
    # takes a parent lock during migration; scoping is enforced app-side.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.ForeignKey(FileSystem, on_delete=models.CASCADE, related_name="canvas_source_versions")
    parent_version = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    # Verifiable content address: hex SHA-256 of the canonical serialized project.
    source_hash = models.CharField(max_length=64)
    # Immutable object-storage key of the serialized project (private namespace).
    source_object_key = models.TextField()
    # Size in bytes of the canonical (uncompressed) serialization.
    source_size = models.PositiveIntegerField()

    # Attribution: the task/run that published this version, when one did.
    task_id = models.UUIDField(null=True, blank=True)
    task_run_id = models.UUIDField(null=True, blank=True)
    prompt = models.TextField(null=True, blank=True)
    # Id of the legacy meta.versions entry created by the same publish, so
    # in-meta history and normalized rows stay correlatable during rollout.
    legacy_version_id = models.CharField(max_length=64, null=True, blank=True)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["canvas", "-created_at"], name="canvas_source_version_recency")]


class CanvasBuild(TeamScopedRootMixin, UUIDModel):
    """Lifecycle record of one build of a canvas source version.

    A failed build records diagnostics but never replaces the canvas's
    last-known-good artifact; the live pointer (`publishedBuildId` in the
    canvas's meta) only advances when a build completes and its source version
    is still the canvas's current head.
    """

    STATUS_QUEUED = "queued"
    STATUS_BUILDING = "building"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUSES = [STATUS_QUEUED, STATUS_BUILDING, STATUS_READY, STATUS_FAILED]

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.ForeignKey(FileSystem, on_delete=models.CASCADE, related_name="canvas_builds")
    source_version = models.ForeignKey(CanvasSourceVersion, on_delete=models.CASCADE, related_name="builds")

    status = models.CharField(max_length=16, default=STATUS_QUEUED)
    # Object-storage prefix the immutable artifact files live under (set when ready).
    artifact_object_prefix = models.TextField(null=True, blank=True)
    # Hex SHA-256 over the artifact manifest — the integrity anchor for loaders.
    integrity = models.CharField(max_length=64, null=True, blank=True)
    # Bounded structured diagnostics (full logs belong in log storage, not here).
    diagnostics = models.JSONField(default=list, blank=True)
    # The frozen artifact manifest (entry, assets, versions, capabilities).
    manifest = models.JSONField(null=True, blank=True)
    # Pinned builds are retained for the lifetime of the canvas.
    pinned = models.BooleanField(default=False)
    attempt_count = models.PositiveIntegerField(default=0)
    lease_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["canvas", "-created_at"], name="canvas_build_recency")]
