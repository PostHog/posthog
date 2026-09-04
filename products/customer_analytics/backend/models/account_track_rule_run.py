from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UUIDModel


class AccountTrackRuleRunTrigger(models.TextChoices):
    MANUAL = "manual", "manual"
    SCHEDULED = "scheduled", "scheduled"


class AccountTrackRuleRunStatus(models.TextChoices):
    PENDING = "pending", "pending"
    RUNNING = "running", "running"
    COMPLETED = "completed", "completed"
    FAILED = "failed", "failed"
    STALE = "stale", "stale"


class AccountTrackRuleRun(TeamScopedRootMixin, UUIDModel, CreatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    config_version = models.PositiveIntegerField()
    trigger = models.CharField(
        max_length=20,
        choices=AccountTrackRuleRunTrigger.choices,
        default=AccountTrackRuleRunTrigger.MANUAL,
    )
    status = models.CharField(
        max_length=20,
        choices=AccountTrackRuleRunStatus.choices,
        default=AccountTrackRuleRunStatus.PENDING,
    )
    idempotency_key = models.UUIDField()

    eligible_active = models.PositiveIntegerField(default=0)
    skipped_churned = models.PositiveIntegerField(default=0)
    tracked = models.PositiveIntegerField(default=0)
    ignored = models.PositiveIntegerField(default=0)
    newly_ignored = models.PositiveIntegerField(default=0)
    restored = models.PositiveIntegerField(default=0)
    processed = models.PositiveIntegerField(default=0)
    last_account_id = models.UUIDField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "idempotency_key"],
                name="ca_track_run_team_idem_uniq",
            )
        ]
        indexes = [models.Index(fields=["team", "-created_at"], name="ca_track_run_team_created")]
