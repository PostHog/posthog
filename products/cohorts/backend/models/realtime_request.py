from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.cohorts.backend.models.backfill import CohortBackfillKind


class RealtimeCohortRequestKind(models.TextChoices):
    ENABLE = "enable", "Enable"
    BACKFILL = "backfill", "Backfill"


class RealtimeCohortRequestState(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    DONE = "done", "Done"
    # A rule said no, and `error` says which one.
    REFUSED = "refused", "Refused"
    # An unexpected exception, or a request that never finished.
    FAILED = "failed", "Failed"


UNFINISHED_REQUEST_STATES = (RealtimeCohortRequestState.QUEUED, RealtimeCohortRequestState.RUNNING)


class RealtimeCohortRequest(TeamScopedRootMixin, UUIDModel):
    """Work that staff asked the realtime cohort pipeline to do for a team. A Celery task carries it out."""

    # No FK constraints, because creating one locks the hot posthog_team and posthog_user tables while migrating.
    # No index of its own, because both indexes below start with the team.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    kind = models.CharField(max_length=16, choices=RealtimeCohortRequestKind.choices)
    backfill_kind = models.CharField(max_length=32, choices=CohortBackfillKind.choices, null=True)
    # Null means every eligible cohort of the team.
    cohort_ids = ArrayField(models.IntegerField(), null=True)
    skip_scan_limit = models.BooleanField(default=False)
    state = models.CharField(
        max_length=16, choices=RealtimeCohortRequestState.choices, default=RealtimeCohortRequestState.QUEUED
    )
    requested_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, db_constraint=False, related_name="+"
    )
    reason = models.TextField(blank=True, default="")
    # On a `done` request, a warning.
    error = models.TextField(blank=True, default="")
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "cohort_realtime_request"
        indexes = [models.Index(fields=["team", "-created_at"], name="cohort_rtr_team_created_idx")]
        constraints = [
            # Makes a double submit fail, and keeps two requests of the same team from running together.
            models.UniqueConstraint(
                fields=["team"], condition=Q(state__in=UNFINISHED_REQUEST_STATES), name="cohort_rtr_unfinished_team_uq"
            ),
            models.CheckConstraint(
                condition=Q(kind=RealtimeCohortRequestKind.BACKFILL, backfill_kind__isnull=False)
                | Q(kind=RealtimeCohortRequestKind.ENABLE, backfill_kind__isnull=True),
                name="cohort_rtr_backfill_kind_ck",
            ),
        ]
