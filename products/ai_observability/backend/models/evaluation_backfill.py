from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class EvaluationBackfillStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


ACTIVE_BACKFILL_STATUSES = (EvaluationBackfillStatus.RUNNING,)


class EvaluationBackfill(TeamScopedRootMixin, UUIDModel):
    """One historical run of an evaluation over a date window.

    The row is the source of truth for progress: the Temporal workflow reads the cursor at every
    tick and writes it back, so a worker restart resumes where it stopped.
    """

    evaluation = models.ForeignKey("ai_observability.Evaluation", on_delete=models.CASCADE, related_name="backfills")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)

    window_start = models.DateTimeField(help_text="Inclusive lower bound of the window, by unit timestamp.")
    window_end = models.DateTimeField(help_text="Exclusive upper bound of the window; clamped to now at creation.")

    status = models.CharField(
        max_length=16, choices=EvaluationBackfillStatus.choices, default=EvaluationBackfillStatus.RUNNING
    )

    # Frozen at creation so an edit to the evaluation mid-run does not change what the walk matches.
    target = models.CharField(max_length=20, help_text="Evaluation target frozen at creation.")
    conditions = models.JSONField(
        default=list,
        help_text="Condition sets used for this backfill: [{properties: [...], rollout_percentage: float}].",
    )
    rerun_existing = models.BooleanField(
        default=False, help_text="When true, units that already have a result from this evaluation are evaluated again."
    )

    # Keyset cursor over (unit timestamp DESC, unit id DESC). Null until the first batch is dispatched.
    cursor_timestamp = models.DateTimeField(null=True, blank=True)
    cursor_unit_id = models.CharField(max_length=512, blank=True, default="")

    total_count = models.PositiveIntegerField(help_text="Units matched at creation; the ceiling on dispatched_count.")
    dispatched_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(
        default=0, help_text="Units whose child workflow already existed, so the live path had them."
    )

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["evaluation"],
                condition=models.Q(status="running"),
                name="aio_eval_backfill_one_active_per_evaluation",
            ),
            models.CheckConstraint(
                condition=models.Q(window_start__lt=models.F("window_end")),
                name="aio_eval_backfill_window_start_before_end",
            ),
        ]
        indexes = [models.Index(fields=["team", "created_at"], name="aio_eval_backfill_team_created")]

    def save(self, *args, **kwargs) -> None:
        if self._state.adding:
            evaluation_team_id = self.evaluation.team_id
            if self.team_id and self.team_id != evaluation_team_id:
                raise ValueError("EvaluationBackfill.team_id must match evaluation.team_id")
            self.team_id = evaluation_team_id
        super().save(*args, **kwargs)
