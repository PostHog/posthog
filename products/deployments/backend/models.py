"""Django models for the Deployments product.

Scaffold only — fields and choices land here so other commits on
`feat/deployments` can build behavior on top. Business logic, signals,
and activity describers will be filled in later.
"""

from __future__ import annotations

import uuid

from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.product_mixin import ProductTeamModel


class Deployment(ModelActivityMixin, ProductTeamModel):
    """A single deployment of a project's site.

    `team_id` is inherited from `ProductTeamModel` as a plain
    `BigIntegerField` — no cross-DB FK to `Team`. All reads go through
    the fail-closed `TeamScopedManager`.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        INITIALIZING = "initializing", "Initializing"
        BUILDING = "building", "Building"
        READY = "ready", "Ready"
        ERROR = "error", "Error"
        CANCELLED = "cancelled", "Cancelled"

    class TriggerKind(models.TextChoices):
        GIT = "git", "Git"
        REDEPLOY = "redeploy", "Redeploy"
        ROLLBACK = "rollback", "Rollback"
        SEED = "seed", "Seed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    commit_sha = models.CharField(max_length=64, blank=True, default="")
    commit_message = models.TextField(blank=True, default="")
    commit_author_name = models.CharField(max_length=255, blank=True, default="")
    commit_author_email = models.CharField(max_length=255, blank=True, default="")

    repo_url = models.URLField(max_length=1024, blank=True, default="")
    branch = models.CharField(max_length=255, blank=True, default="")

    deployment_url = models.URLField(max_length=1024, blank=True, default="")
    preview_image_url = models.URLField(max_length=1024, blank=True, default="")

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
        default=TriggerKind.GIT,
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("team_id", "-created_at"), name="deploy_team_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Deployment {self.id} ({self.status})"
