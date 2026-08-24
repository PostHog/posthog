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

    ``kind`` splits the model into three shapes sharing this lifecycle:

    - ``freeform`` — a standalone app; its source project compiles to one artifact.
    - ``component`` — a reusable widget other canvases place on a grid. Same
      source/build pipeline as freeform, plus a config schema and grid size
      snapshotted onto each version. Visibility rides the channel like any
      canvas: a component in a personal channel is private, in a team channel
      it is the team's.
    - ``grid`` — a composition of components. Its "source" is a layout document
      (placements referencing component canvases), so publishing a grid
      validates and versions the layout without queuing a build.
    """

    KIND_FREEFORM = "freeform"
    KIND_GRID = "grid"
    KIND_COMPONENT = "component"
    KINDS = [KIND_FREEFORM, KIND_GRID, KIND_COMPONENT]

    # db_constraint=False: a real FK constraint to the hot posthog_team table
    # takes a parent lock during migration; scoping is enforced app-side.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    # Channels are the tasks product's model; every canvas is filed into one.
    channel = models.ForeignKey("tasks.Channel", on_delete=models.CASCADE, db_constraint=False, related_name="canvases")

    name = models.CharField(max_length=400)
    kind = models.CharField(max_length=16, default=KIND_FREEFORM)
    # Short prose describing what the canvas is/does. For components this is
    # the store-search text agents match against, so it should say what the
    # widget shows and what its config controls.
    description = models.TextField(blank=True, default="")
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
        indexes = [
            models.Index(fields=["channel", "-created_at"], name="canvas_channel_recency"),
            # The component store lists/searches by team + kind; freeform rows
            # (the overwhelming majority) stay out of the index.
            models.Index(
                fields=["team", "kind"],
                condition=~Q(kind="freeform"),
                name="canvas_kind_store",
            ),
        ]


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

    # For component-kind canvases: the version's placement contract (config
    # schema, grid size), denormalized from the stored source so the store and
    # layout validation can read it without hitting object storage. Null for
    # freeform/grid versions and component versions that predate it.
    component_meta = models.JSONField(null=True, blank=True)

    # True while the version is a staged draft: stored and built like any other
    # version, but never the canvas head, so its build can't go live. Promoting
    # clears the flag; after that the version is indistinguishable from a publish.
    draft = models.BooleanField(default=False)

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


class CanvasHomePreference(TeamScopedRootMixin, UUIDModel):
    """One user's home-canvas selection within a team.

    Home is a pointer to an ordinary canvas (normally a grid canvas in the
    user's personal channel), not a flag on the canvas itself — a canvas-side
    marker was tried before (``is_home``) and retired because it entangled
    canvas lifecycle with surface lifecycle. The FK cascade only clears the
    pointer on a hard delete of the team or channel; the canvas delete endpoint
    is a soft delete (``deleted=True``), so a pointer at a soft-deleted canvas
    survives. The home reader must treat a pointer whose canvas is deleted as no
    home set — filter ``canvas__deleted=False`` — and re-provision on next open.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.ForeignKey(Canvas, on_delete=models.CASCADE, related_name="+")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_canvas_home_preference"
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="canvas_home_one_per_user_team"),
        ]


class CanvasState(TeamScopedRootMixin, UUIDModel):
    """One key of a canvas's runtime key-value store (the ``ph.state`` verb).

    ``user`` rows belong to one viewer; ``shared`` rows to the canvas itself.
    Values are application data written from viewer sessions — never secrets —
    and bounded at write time (value size, keys per scope), which keeps every
    access a point lookup and table growth capped by canvas count.
    """

    SCOPE_USER = "user"
    SCOPE_SHARED = "shared"
    SCOPES = [SCOPE_USER, SCOPE_SHARED]

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.ForeignKey(Canvas, on_delete=models.CASCADE, related_name="state_entries")
    scope = models.CharField(max_length=8)
    # The owning viewer for user-scoped rows; always null for shared rows.
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)
    key = models.CharField(max_length=200)
    value = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_canvas_state"
        constraints = [
            # Postgres treats NULLs as distinct, so shared rows (user NULL) get
            # their own uniqueness arm instead of one four-column constraint.
            models.UniqueConstraint(
                fields=["canvas", "scope", "user", "key"],
                condition=Q(user__isnull=False),
                name="canvas_state_user_key",
            ),
            models.UniqueConstraint(
                fields=["canvas", "scope", "key"],
                condition=Q(user__isnull=True),
                name="canvas_state_shared_key",
            ),
        ]
