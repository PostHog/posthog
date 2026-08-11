from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class Canvas(TeamScopedRootMixin, UUIDModel):
    """A canvas document: an agent-built, sandboxed browser app filed in a channel.

    The document's source lives in append-only ``CanvasSourceVersion`` rows
    (content in object storage); built artifacts hang off ``CanvasBuild`` rows.
    ``current_source_version`` is the editable head (publish advances it,
    revert moves it back) and ``published_build`` is the live artifact pointer —
    it only advances when a build completes for a version that is still the head.
    """

    # db_constraint=False: a real FK constraint to the hot posthog_team table
    # takes a parent lock during migration; scoping is enforced app-side.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    # Channels are the tasks product's model; every canvas is filed into one.
    channel = models.ForeignKey("tasks.Channel", on_delete=models.CASCADE, db_constraint=False, related_name="canvases")

    name = models.CharField(max_length=400)
    template_id = models.CharField(max_length=64, default="freeform")
    # Author-written markdown handed to generation tasks as background context.
    context = models.TextField(blank=True, default="")
    # The task currently generating/editing this canvas. A plain UUID rather
    # than a FK: Task lives in the tasks app and a schema-level FK would chain
    # the two products' migrations together for a soft pointer.
    generation_task_id = models.UUIDField(null=True, blank=True)
    # Set when the canvas is pinned to its channel (shared across users).
    pinned_at = models.DateTimeField(null=True, blank=True)

    current_source_version = models.ForeignKey(
        "canvas.CanvasSourceVersion", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    published_build = models.ForeignKey(
        "canvas.CanvasBuild", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Single-file source carried over from the pre-relational data model. Read
    # only when a canvas has no source versions yet; the next publish creates a
    # real version and this field stops mattering.
    legacy_code = models.TextField(null=True, blank=True)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "posthog_canvas"
        indexes = [models.Index(fields=["channel", "-created_at"], name="canvas_channel_recency")]


class CanvasSourceVersion(TeamScopedRootMixin, UUIDModel):
    """One immutable published source project of a canvas.

    The project content itself lives in object storage (private, content
    addressed); this row is the control-plane record: pointers, hashes,
    attribution, and lineage. Rows are append-only — a publish never rewrites
    an existing version.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.ForeignKey(Canvas, on_delete=models.CASCADE, related_name="source_versions")
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

    # Snapshot of the project's declared capabilities manifest, denormalized
    # from the stored source so capability changes can be diffed and audited
    # without reading object storage. Null for versions that predate it.
    capabilities = models.JSONField(null=True, blank=True)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "posthog_canvas_source_version"
        indexes = [models.Index(fields=["canvas", "-created_at"], name="canvas_source_version_recency")]


class CanvasBuild(TeamScopedRootMixin, UUIDModel):
    """Lifecycle record of one build of a canvas source version.

    A failed build records diagnostics but never replaces the canvas's
    last-known-good artifact; the live pointer (``Canvas.published_build``)
    only advances when a build completes and its source version is still the
    canvas's current head.
    """

    STATUS_QUEUED = "queued"
    STATUS_BUILDING = "building"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    ACTIVE_STATUSES = [STATUS_QUEUED, STATUS_BUILDING]

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.ForeignKey(Canvas, on_delete=models.CASCADE, related_name="builds")
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
    # Set every time the build is handed to the worker queue. The stuck-build
    # sweeper keys redelivery staleness off this (not created_at), so a retry of
    # an old failed build isn't mistaken for a lost enqueue.
    enqueued_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_canvas_build"
        indexes = [
            models.Index(fields=["canvas", "-created_at"], name="canvas_build_recency"),
            # The team build cap and the stuck-build sweeper both scan only
            # in-flight rows, which are a tiny fraction of the table.
            models.Index(
                fields=["team", "status"],
                condition=Q(status__in=["queued", "building"]),
                name="canvas_build_active",
            ),
            # The retention sweep scans only prunable rows (unpinned, artifacts
            # still present) by age.
            models.Index(
                fields=["finished_at"],
                condition=Q(pinned=False, artifact_object_prefix__isnull=False),
                name="canvas_build_retention",
            ),
        ]
