"""The durable record of one attempt to populate a static cohort."""

from django.db import models
from django.db.models import Q
from django.utils import timezone as django_timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class CohortPopulationSource(models.TextChoices):
    LIST = "list", "List"
    QUERY = "query", "Query"
    FILTERS = "filters", "Filters"
    FEATURE_FLAG = "feature_flag", "Feature flag"
    # Writes the ClickHouse membership a cohort already holds into Postgres, and nothing else. Its
    # own source so it can never be read as an import: a reconciliation repairs the subset that
    # reached ClickHouse, which says nothing about whether the original upload finished. Keeping
    # the two apart is what stops a repaired cohort from reporting a complete import it never had.
    RECONCILE = "reconcile", "Reconcile"


class CohortPopulationPhase(models.TextChoices):
    """The next kind of work; flag sources alternate fetching and writing pages."""

    MATERIALIZING_SOURCE = "materializing_source", "Materializing source"
    WRITING_MEMBERSHIP = "writing_membership", "Writing membership"
    SYNCHRONIZING = "synchronizing", "Synchronizing"
    FINALIZING = "finalizing", "Finalizing"
    DONE = "done", "Done"


class CohortPopulationRecoveryAction(models.TextChoices):
    """What a person can do about an operation right now."""

    RETRY = "retry", "Retry"
    ABANDON = "abandon", "Abandon"
    REUPLOAD = "reupload", "Re-upload"


class CohortPopulationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    ABANDONED = "abandoned", "Abandoned"


ACTIVE_COHORT_POPULATION_STATUSES = (
    CohortPopulationStatus.PENDING,
    CohortPopulationStatus.RUNNING,
    CohortPopulationStatus.RETRY_SCHEDULED,
)

UNRESOLVED_COHORT_POPULATION_STATUSES = (*ACTIVE_COHORT_POPULATION_STATUSES, CohortPopulationStatus.FAILED)

RESOLVED_COHORT_POPULATION_STATUSES = tuple(
    status for status in CohortPopulationStatus if status not in UNRESOLVED_COHORT_POPULATION_STATUSES
)


class CohortPopulationOperation(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    cohort = models.ForeignKey("cohorts.Cohort", on_delete=models.CASCADE, related_name="population_operations")
    created_by_id = models.BigIntegerField(null=True, blank=True)

    source = models.CharField(max_length=32, choices=CohortPopulationSource.choices)
    source_config = models.JSONField(default=dict)
    phase = models.CharField(max_length=32, choices=CohortPopulationPhase.choices)
    status = models.CharField(
        max_length=32, choices=CohortPopulationStatus.choices, default=CohortPopulationStatus.PENDING
    )

    input_manifest = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Where the retained input lives and what it holds: object-storage prefix, chunk count, "
            "identifier type and total. Null when the source needs no retained input."
        ),
    )
    input_expires_at = models.DateTimeField(null=True, blank=True)
    input_deleted_at = models.DateTimeField(null=True, blank=True)

    progress = models.JSONField(
        default=dict,
        help_text="Resume point for the current phase — see `population.progress.PopulationProgress`.",
    )

    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=6)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    claim_token = models.UUIDField(
        null=True,
        blank=True,
        help_text=(
            "Identifies the attempt that currently owns this operation. Every progress write is "
            "conditioned on it, so a replaced worker's late write lands on nothing."
        ),
    )
    claimed_by = models.CharField(max_length=255, blank=True, default="")
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    abandon_requested_at = models.DateTimeField(null=True, blank=True)

    error_code = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="A `CohortErrorCode` value. Bounded and safe to show — never raw exception text.",
    )

    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cohort_population_operations"
        indexes = [
            # The dispatcher sweeps every team's unresolved operations, so it cannot use a
            # team-prefixed index. Partial on status keeps that scan proportional to the live set
            # rather than to the table's ever-growing terminal history.
            models.Index(
                fields=["next_attempt_at"],
                condition=Q(status__in=UNRESOLVED_COHORT_POPULATION_STATUSES),
                name="cohort_pop_unresolved_idx",
            ),
            models.Index(fields=["cohort", "-created_at"], name="cohort_pop_cohort_created_idx"),
            # The input reaper is likewise fleet-wide, and only ever wants rows still holding input.
            models.Index(
                fields=["input_expires_at"],
                condition=Q(input_manifest__isnull=False),
                name="cohort_pop_input_expiry_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["cohort"],
                condition=Q(status__in=UNRESOLVED_COHORT_POPULATION_STATUSES),
                name="cohort_pop_unresolved_cohort_uq",
            ),
        ]

    def __str__(self) -> str:
        return f"CohortPopulationOperation({self.pk}, cohort={self.cohort_id}, {self.source}/{self.status})"
