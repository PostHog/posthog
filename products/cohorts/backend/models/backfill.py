from django.db import models
from django.db.models import Q
from django.utils import timezone as django_timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, UUIDTModel


class CohortBackfillKind(models.TextChoices):
    BEHAVIORAL = "behavioral", "Behavioral"
    PERSON_PROPERTY = "person_property", "Person property"


class CohortBackfillTrigger(models.TextChoices):
    TEAM_ENABLEMENT = "team_enablement", "Team enablement"
    COHORT_CREATED = "cohort_created", "Cohort created"
    COHORT_EDITED = "cohort_edited", "Cohort edited"
    DISASTER_RECOVERY = "disaster_recovery", "Disaster recovery"


class CohortBackfillScope(models.TextChoices):
    TEAM = "team", "Team"
    COHORT = "cohort", "Cohort"


class CohortBackfillRunStatus(models.TextChoices):
    AWAITING_BOUNDARY = "awaiting_boundary", "Awaiting boundary"
    BLOCKED = "blocked", "Blocked"
    SEEDING = "seeding", "Seeding"
    RECONCILING = "reconciling", "Reconciling"
    COMPLETED = "completed", "Completed"
    SUPERSEDED = "superseded", "Superseded"
    CANCELLED = "cancelled", "Cancelled"
    FAILED = "failed", "Failed"


ACTIVE_COHORT_BACKFILL_RUN_STATUSES = (
    CohortBackfillRunStatus.AWAITING_BOUNDARY,
    CohortBackfillRunStatus.BLOCKED,
    CohortBackfillRunStatus.SEEDING,
    CohortBackfillRunStatus.RECONCILING,
)


class CohortBackfillChunkStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SCANNING = "scanning", "Scanning"
    PRODUCED = "produced", "Produced"
    CONFIRMED = "confirmed", "Confirmed"
    FAILED = "failed", "Failed"


class CohortBackfillRun(TeamScopedRootMixin, UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    cohort = models.ForeignKey(
        "cohorts.Cohort", on_delete=models.SET_NULL, null=True, blank=True, related_name="backfill_runs"
    )
    created_by_id = models.BigIntegerField(null=True, blank=True)
    backfill_kind = models.CharField(
        max_length=32, choices=CohortBackfillKind.choices, default=CohortBackfillKind.BEHAVIORAL
    )
    trigger_kind = models.CharField(max_length=32, choices=CohortBackfillTrigger.choices)
    scope = models.CharField(max_length=16, choices=CohortBackfillScope.choices)
    status = models.CharField(
        max_length=32, choices=CohortBackfillRunStatus.choices, default=CohortBackfillRunStatus.AWAITING_BOUNDARY
    )
    timezone = models.CharField(max_length=240)
    boundary_at = models.DateTimeField(null=True, blank=True)
    boundary_established_at = models.DateTimeField(null=True, blank=True)
    pinned = models.JSONField(default=dict)
    preconditions = models.JSONField(default=dict)
    reconcile_hwms = models.JSONField(null=True, blank=True)
    blocked_reason = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="superseded_runs"
    )
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cohort_backfill_runs"
        indexes = [
            models.Index(fields=["team", "status"], name="cohort_bfr_team_status_idx"),
            models.Index(fields=["team", "-created_at"], name="cohort_bfr_team_created_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["cohort"],
                condition=Q(cohort__isnull=False, status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES),
                name="cohort_bfr_active_cohort_uq",
            ),
            models.UniqueConstraint(
                fields=["team"],
                condition=Q(scope=CohortBackfillScope.TEAM, status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES),
                name="cohort_bfr_active_team_uq",
            ),
        ]


class CohortBackfillRunCohort(TeamScopedRootMixin, UUIDModel):
    run = models.ForeignKey(CohortBackfillRun, on_delete=models.CASCADE, related_name="run_cohorts")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    cohort = models.ForeignKey("cohorts.Cohort", on_delete=models.CASCADE, related_name="backfill_participations")
    filters_shape_hash = models.CharField(max_length=64)
    behavioral_filters_shape_hash = models.CharField(max_length=64, default="")
    pinned_filters = models.JSONField()
    stamped_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "cohort_backfill_run_cohorts"
        constraints = [
            models.UniqueConstraint(fields=["run", "cohort"], name="cohort_bfrc_run_cohort_uq"),
        ]


class CohortBackfillChunk(TeamScopedRootMixin, UUIDModel):
    run = models.ForeignKey(CohortBackfillRun, on_delete=models.CASCADE, related_name="chunks")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    day = models.DateField()
    band = models.SmallIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=CohortBackfillChunkStatus.choices, default=CohortBackfillChunkStatus.PENDING
    )
    claim_epoch = models.IntegerField(default=0)
    claimed_by = models.CharField(max_length=255, blank=True, default="")
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    s_chunk_at = models.DateTimeField(null=True, blank=True)
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    tiles_produced = models.BigIntegerField(default=0)
    produce_hwms = models.JSONField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cohort_backfill_chunks"
        indexes = [
            models.Index(fields=["run", "status", "day"], name="cohort_bfc_run_status_day_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["run", "day", "band"], name="cohort_bfc_run_day_band_uq"),
        ]
