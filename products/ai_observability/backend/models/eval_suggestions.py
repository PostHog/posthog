from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class EvalSuggestionKind(models.TextChoices):
    NEW_HOG = "new_hog", "New Hog eval"
    NEW_LLM_JUDGE = "new_llm_judge", "New LLM judge"
    FIX_EVAL = "fix_eval", "Fix an evaluation"


class EvalSuggestionStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    ACCEPTED = "accepted", "Accepted"
    DISMISSED = "dismissed", "Dismissed"
    EXPIRED = "expired", "Expired"


class EvalSuggestionDismissReason(models.TextChoices):
    NOT_RELEVANT = "not_relevant", "Not relevant"
    ALREADY_COVERED = "already_covered", "Already covered"
    TOO_NOISY = "too_noisy", "Too noisy"
    FIXED_CAUSE = "fixed_cause", "Fixed the cause"


class EvalSuggestionRunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class EvalSuggestionRunTrigger(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    FIRST_VISIT = "first_visit", "First visit"
    MANUAL = "manual", "Manual"


class EvalSuggestionRun(TeamScopedRootMixin, UUIDModel):
    """One pipeline run for one team. The API shows the suggestions of the team's latest completed run,
    so a run that fails halfway never replaces a complete set of cards with a partial one."""

    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    trigger = models.CharField(max_length=16, choices=EvalSuggestionRunTrigger.choices)
    status = models.CharField(
        max_length=16, choices=EvalSuggestionRunStatus.choices, default=EvalSuggestionRunStatus.RUNNING
    )
    # Per stage: {"status": "ok" | "skipped" | "failed", "detail": str, ...counts}.
    stages = models.JSONField(default=dict)
    # What one stage hands the next while the run works: the sampled trace ids and the candidate cards, never
    # trace content. Each stage is its own Temporal activity, and payloads must not carry customer data.
    # Cleared when the run completes or fails.
    handoff = models.JSONField(default=dict, blank=True)
    # Provider spend of the paid drafting stage, summed per batch to enforce the per-run budget.
    cost_usd = models.FloatField(default=0)
    batch_id = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "status", "-completed_at"], name="llma_evalsugg_run_latest"),
            models.Index(fields=["batch_id"], name="llma_evalsugg_run_batch", condition=~models.Q(batch_id="")),
        ]


class EvalSuggestion(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    # The (run, dedupe_key) unique index covers lookups by run.
    run = models.ForeignKey(EvalSuggestionRun, on_delete=models.CASCADE, db_index=False, related_name="suggestions")
    kind = models.CharField(max_length=16, choices=EvalSuggestionKind.choices)
    # Catalog template or adapted check this suggestion was built from.
    template_key = models.CharField(max_length=64, blank=True, default="")
    # Identity across runs, so a dismissal or an accepted card suppresses the same suggestion next week. An
    # evaluation created from the suggestion keeps it through `created_evaluation`, which exact dedupe reads.
    dedupe_key = models.CharField(max_length=255)
    # The card's words: the problem in the app's terms, then what adding the evaluation does and costs.
    # `reason` holds how the problem was measured, which the card shows on request.
    headline = models.CharField(max_length=400)
    outcome = models.TextField()
    reason = models.TextField()
    # Evaluation API input without conditions: accept adds `filters` and `rollout_percentage` as its
    # one condition set. For fix_eval it is the PATCH body for `target_evaluation`.
    draft = models.JSONField(default=dict)
    filters = models.JSONField(default=list)
    rollout_percentage = models.FloatField(default=100)
    # Only Hog checks carry a rate, because only they are measured exactly. Judges stay "possible".
    measured_failure_rate = models.FloatField(null=True, blank=True)
    sample_size = models.PositiveIntegerField(null=True, blank=True)
    # [{"trace_id": str, "reason": str}], one line each.
    evidence = models.JSONField(default=list)
    score = models.FloatField(default=0)
    estimated_weekly_runs = models.PositiveIntegerField(null=True, blank=True)
    estimated_weekly_cost_usd = models.FloatField(null=True, blank=True)
    mean_input_tokens = models.PositiveIntegerField(null=True, blank=True)
    # The model whose price the weekly cost assumes. Accept runs a judge on the active key's default model.
    judge_model = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=EvalSuggestionStatus.choices, default=EvalSuggestionStatus.PROPOSED
    )
    dismiss_reason = models.CharField(max_length=32, choices=EvalSuggestionDismissReason.choices, null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_evaluation = models.ForeignKey(
        "ai_observability.Evaluation", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    target_evaluation = models.ForeignKey(
        "ai_observability.Evaluation", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    similar_evaluation = models.ForeignKey(
        "ai_observability.Evaluation", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "dedupe_key"], name="llma_evalsugg_unique_per_run"),
        ]
        indexes = [
            models.Index(fields=["team", "dedupe_key", "status"], name="llma_evalsugg_dedupe"),
        ]


class EvalSuggestionTeamState(TeamScopedRootMixin):
    """Team extension: when someone last loaded the suggestions, and the day of the last first-visit run."""

    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    last_visited_at = models.DateTimeField(null=True, blank=True, db_index=True)
    first_visit_run_on = models.DateField(null=True, blank=True)
