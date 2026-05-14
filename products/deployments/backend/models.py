"""Django models for the Deployments product.

Three models:
- DeploymentProject — a connected repo + Cloudflare Pages target + build config.
- Deployment — one build attempt against a project at a specific commit.
- DeploymentEvent — append-only audit log per deployment (drives the timeline UI).

All inherit ProductTeamModel: team_id is a plain BigIntegerField (no FK to Team)
and queries are fail-closed via TeamScopedManager. DeploymentProject and
Deployment also inherit ModelActivityMixin so create/update/delete are surfaced
through the standard activity log. DeploymentEvent is itself the audit log —
no second log on top.
"""

from __future__ import annotations

from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import DeletedMetaFields, uuid7


class DeploymentProject(ModelActivityMixin, ProductTeamModel, DeletedMetaFields):
    """A connected repo + its Cloudflare Pages hosting target.

    One DeploymentProject per Cloudflare Pages project. A team may own
    multiple projects (different repos). The `current_deployment` pointer
    is the single source of truth for "what's serving now"; it is set
    explicitly on a successful build or rollback rather than derived as
    "most recent READY", because Cloudflare's rollback API can promote a
    non-latest deployment to current.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_by_id = models.BigIntegerField(null=True, blank=True)

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80)

    # Source
    repo_url = models.URLField(max_length=1024)
    default_branch = models.CharField(max_length=255, default="main")
    # Existing PostHog GitHub integration used for repo/branch access. These
    # are plain ids because integrations live in the main app and Deployments
    # keeps product-owned tenant data behind ProductTeamModel.team_id.
    github_integration_id = models.BigIntegerField(null=True, blank=True)
    github_repo_id = models.BigIntegerField(null=True, blank=True)

    # Build config
    # Null = build worker infers the command from `framework` (or auto-detects
    # if framework is also null). Users can pin an explicit command via PATCH.
    build_command = models.TextField(null=True, blank=True, default=None)
    output_dir = models.CharField(max_length=255, default="dist")
    framework = models.CharField(max_length=50, null=True, blank=True)
    inject_posthog_snippet = models.BooleanField(default=False)

    # Hosting (Cloudflare Pages)
    cloudflare_project_name = models.CharField(max_length=255, blank=True, default="")
    subdomain = models.CharField(max_length=255, blank=True, default="")
    cloudflare_ready_at = models.DateTimeField(null=True, blank=True)

    # String-ref + null avoids the circular-FK chicken-and-egg with Deployment
    # in the initial migration. Set on ready-transition or rollback.
    current_deployment = models.ForeignKey(
        "deployments.Deployment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Slug is the user-facing subdomain handle; uniqueness scoped to live rows
            # (matches the soft-delete pattern at posthog/models/llm_prompt.py:38-48).
            models.UniqueConstraint(
                fields=["team_id", "slug"],
                condition=models.Q(deleted=False) | models.Q(deleted__isnull=True),
                name="unique_deploymentproject_slug_per_team",
            ),
            models.UniqueConstraint(
                fields=("team_id", "github_repo_id"),
                condition=models.Q(github_repo_id__isnull=False)
                & (models.Q(deleted=False) | models.Q(deleted__isnull=True)),
                name="deploy_project_team_repo_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "-created_at"]),
            models.Index(fields=("team_id", "github_integration_id"), name="deploy_project_team_int_idx"),
        ]

    def __str__(self) -> str:
        return f"DeploymentProject {self.slug} ({self.id})"


class Deployment(ModelActivityMixin, ProductTeamModel):
    """A single deployment of a project's site.

    `team_id` is inherited from `ProductTeamModel` as a plain `BigIntegerField`
    — no cross-DB FK to `Team`. All reads go through the fail-closed
    `TeamScopedManager`.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        INITIALIZING = "initializing", "Initializing"
        BUILDING = "building", "Building"
        READY = "ready", "Ready"
        ERROR = "error", "Error"
        CANCELLED = "cancelled", "Cancelled"

    NON_TERMINAL_STATUSES: tuple[str, ...] = (Status.QUEUED, Status.INITIALIZING, Status.BUILDING)
    TERMINAL_STATUSES: tuple[str, ...] = (Status.READY, Status.ERROR, Status.CANCELLED)

    class TriggerKind(models.TextChoices):
        MANUAL = "manual", "Manual"
        GIT = "git", "Git"
        REDEPLOY = "redeploy", "Redeploy"
        ROLLBACK = "rollback", "Rollback"
        SEED = "seed", "Seed"

    class ErrorStep(models.TextChoices):
        DISPATCH = "dispatch", "Dispatch"
        CLONE = "clone", "Clone"
        INSTALL = "install", "Install"
        BUILD = "build", "Build"
        PUBLISH = "publish", "Publish"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    # Parent project. CASCADE: hard-deleting a project wipes its deployments.
    # In practice projects soft-delete (deleted=True), so this rarely fires.
    project = models.ForeignKey(
        DeploymentProject,
        on_delete=models.CASCADE,
        related_name="deployments",
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Source — captured at deploy time so changing project.default_branch
    # doesn't rewrite history.
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    commit_message = models.TextField(blank=True, default="")
    commit_author_name = models.CharField(max_length=255, blank=True, default="")
    commit_author_email = models.CharField(max_length=255, blank=True, default="")
    repo_url = models.URLField(max_length=1024, blank=True, default="")
    branch = models.CharField(max_length=255, blank=True, default="")

    # Who clicked deploy. BigIntegerField (not FK) because Team / User live
    # in the main DB and ProductTeamModel doesn't carry FK constraints across.
    triggered_by_user_id = models.BigIntegerField(null=True, blank=True)
    triggered_by_deployment = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    trigger_kind = models.CharField(
        max_length=16,
        choices=TriggerKind.choices,
        default=TriggerKind.MANUAL,
    )

    # Result
    deployment_url = models.URLField(max_length=1024, blank=True, default="")
    preview_image_url = models.URLField(max_length=1024, blank=True, default="")

    # Failure context
    error_message = models.TextField(blank=True, default="")
    error_step = models.CharField(
        max_length=20,
        choices=ErrorStep.choices,
        blank=True,
        default="",
    )

    # External references owned by other streams. Opaque to us; we just
    # store and forward.
    cloudflare_deployment_id = models.CharField(max_length=128, blank=True, default="")
    temporal_workflow_id = models.CharField(max_length=255, blank=True, default="")
    temporal_run_id = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("team_id", "-created_at"), name="deploy_team_created_idx"),
            models.Index(fields=("project", "-created_at"), name="deploy_project_created_idx"),
        ]
        constraints = [
            # Enforces "at most one non-terminal deploy per project" at the DB layer.
            # The 409 the API returns is a friendly surface over the resulting
            # IntegrityError, not a separate check-then-insert (which would race).
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(status__in=("queued", "initializing", "building")),
                name="one_active_deployment_per_project",
            ),
        ]

    def __str__(self) -> str:
        return f"Deployment {self.id} ({self.status})"


class DeploymentEvent(ProductTeamModel):
    """Append-only event log per deployment. Drives timeline, audit, debugging.

    Never updated. Every status transition and lifecycle event is a new row.
    Intentionally NOT a ModelActivityMixin subclass — this IS the audit log.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    deployment = models.ForeignKey(
        Deployment,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(max_length=50)
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["deployment", "occurred_at"])]
        ordering = ("-occurred_at",)

    def __str__(self) -> str:
        return f"DeploymentEvent {self.event_type} on {self.deployment_id}"
