from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class AccountPropertySyncState(TeamScopedRootMixin, models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    saved_query_id = models.UUIDField()
    generation = models.PositiveBigIntegerField(default=0)
    publication_revision = models.PositiveBigIntegerField(default=0)
    active_request_id = models.UUIDField(null=True, blank=True)
    pending_live_request_id = models.UUIDField(null=True, blank=True)
    snapshots = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "saved_query_id"], name="aps_state_team_view_unique")]


class AccountPropertySyncPublication(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    saved_query_id = models.UUIDField()
    job_id = models.CharField(max_length=400)
    revision = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "saved_query_id", "job_id"], name="aps_publication_job_unique")
        ]


class AccountPropertySyncRequest(TeamScopedRootMixin, UUIDModel):
    class Kind(models.TextChoices):
        LIVE = "live", "live"
        STAGED = "staged", "staged"

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        RUNNING = "running", "running"
        COMPLETED = "completed", "completed"
        FAILED = "failed", "failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    saved_query_id = models.UUIDField()
    job_id = models.CharField(max_length=400)
    binding_team_id = models.BigIntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    generation = models.PositiveBigIntegerField(default=0)
    snapshot_revision = models.PositiveBigIntegerField(default=0)
    tokens = models.JSONField(default=dict)
    error = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "saved_query_id", "job_id"], name="aps_request_team_job_unique")
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="aps_pending_request_idx")]


class AccountPropertySyncValueState(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    account = models.ForeignKey("customer_analytics.Account", on_delete=models.CASCADE, related_name="+")
    definition = models.ForeignKey(
        "customer_analytics.CustomPropertyDefinition", on_delete=models.CASCADE, related_name="+"
    )
    source_id = models.UUIDField(null=True, blank=True)
    is_direct_write = models.BooleanField(default=False)
    snapshot_revision = models.PositiveBigIntegerField(default=0)
    generation = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "account", "definition"], name="aps_value_state_key_unique")
        ]
