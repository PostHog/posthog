from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, uuid7

# AUC and confidence scores are probabilities: NULL until measured, otherwise in [0, 1].
# An out-of-range score corrupts model comparison, so the database rejects it too.
UNIT_INTERVAL_VALIDATORS = [MinValueValidator(0.0), MaxValueValidator(1.0)]


def unit_interval_constraint(field: str, name: str) -> models.CheckConstraint:
    return models.CheckConstraint(
        check=models.Q(**{f"{field}__isnull": True}) | models.Q(**{f"{field}__gte": 0.0, f"{field}__lte": 1.0}),
        name=name,
    )


def min_value_constraint(field: str, minimum: int, name: str, *, nullable: bool = False) -> models.CheckConstraint:
    at_least = models.Q(**{f"{field}__gte": minimum})
    if nullable:
        at_least = models.Q(**{f"{field}__isnull": True}) | at_least
    return models.CheckConstraint(check=at_least, name=name)


class AutoresearchPipeline(TeamScopedRootMixin, UUIDModel):
    # Framework internals (admin querysets, FK form fields, raw-id widget lookups) read
    # `_default_manager` with no team context, where the fail-closed `objects` would raise.
    # Route them through this unscoped sibling via `Meta.default_manager_name`, mirroring
    # `ProductTeamModel`; scoped reads stay on `objects`.
    all_teams = models.Manager()

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BOOTSTRAPPING = "bootstrapping", "Bootstrapping"
        RUNNING = "running", "Running"
        CONVERGED = "converged", "Converged"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # db_constraint=False on team/user FKs: creating a real constraint takes a
    # SHARE ROW EXCLUSIVE lock on the hot parent table (see /django-migrations).
    # related_name="+" on every relation into core: a reverse accessor on Team or User is a
    # boundary crossing no import linter can see, and nothing needs to read autoresearch rows
    # off a team. Callers go through the facade.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=False,
        db_constraint=False,
        related_name="+",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    # Prediction target
    target_event = models.CharField(max_length=255, help_text="Event name to predict, e.g. '$pageview'")
    target_definition = models.JSONField(
        default=dict, help_text="Full target definition including filters and positive-label logic"
    )
    horizon_days = models.IntegerField(
        default=7, validators=[MinValueValidator(1)], help_text="Predict whether the target occurs within N days"
    )
    training_lookback_days = models.IntegerField(
        default=180,
        validators=[MinValueValidator(1)],
        help_text="How far back to look for training examples. Larger windows give more data but may include stale behavior.",
    )

    # Population
    training_population = models.JSONField(
        default=dict, help_text="HogQL cohort or filter defining the training population"
    )
    inference_population = models.JSONField(
        default=dict, help_text="HogQL cohort or filter defining the daily scoring population"
    )

    # Schedule and budget
    cadence_days = models.IntegerField(default=1, validators=[MinValueValidator(1)], help_text="Re-score every N days")
    iteration_budget = models.IntegerField(
        default=50, validators=[MinValueValidator(1)], help_text="Max training iterations for the autoresearch loop"
    )
    # Nullable so save() can tell "not supplied" from an explicit value; filled from
    # iteration_budget on first save.
    iteration_budget_remaining = models.IntegerField(
        null=True, blank=True, default=None, validators=[MinValueValidator(0)]
    )

    # Stop criteria
    success_auc = models.FloatField(
        null=True,
        blank=True,
        validators=UNIT_INTERVAL_VALIDATORS,
        help_text="Stop when holdout AUC reaches this threshold",
    )
    plateau_iterations = models.IntegerField(
        default=10,
        validators=[MinValueValidator(1)],
        help_text="Stop if no improvement after this many consecutive iterations",
    )

    # Outputs
    output_person_property = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Person property name for champion scores, e.g. 'predicted_p_pageview'",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_scored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        default_manager_name = "all_teams"
        constraints = [
            min_value_constraint("horizon_days", 1, "autoresearch_horizon_days_positive"),
            min_value_constraint("training_lookback_days", 1, "autoresearch_lookback_days_positive"),
            min_value_constraint("cadence_days", 1, "autoresearch_cadence_days_positive"),
            min_value_constraint("iteration_budget", 1, "autoresearch_iteration_budget_positive"),
            min_value_constraint("plateau_iterations", 1, "autoresearch_plateau_iterations_positive"),
            min_value_constraint(
                "iteration_budget_remaining", 0, "autoresearch_budget_remaining_nonnegative", nullable=True
            ),
            unit_interval_constraint("success_auc", "autoresearch_success_auc_in_unit_range"),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Fill only at creation: a later save must not silently refund an exhausted budget.
        if self._state.adding and self.iteration_budget_remaining is None:
            self.iteration_budget_remaining = self.iteration_budget
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.team_id})"


class PipelineScopedModel(TeamScopedRootMixin, UUIDModel):
    """A row owned by one pipeline. Subclasses declare their own `pipeline` foreign key.

    The row carries team rather than reaching it through pipeline, because
    TeamScopedManager filters on a team column the model itself declares, and save()
    derives it from the parent so a caller cannot file a row under the wrong tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # See AutoresearchPipeline.team: no reverse accessor on the core model.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)

    # See AutoresearchPipeline.all_teams: framework internals need an unscoped
    # `_default_manager`; concrete subclasses set `Meta.default_manager_name = "all_teams"`.
    all_teams = models.Manager()

    # Relations that must belong to the same pipeline as this row. save() rejects a
    # mismatch, so a row cannot mix parents across pipelines.
    _pipeline_bound_relations: ClassVar[tuple[str, ...]] = ()

    if TYPE_CHECKING:
        # Subclasses declare the pipeline FK; this names its attname for the shared save().
        pipeline_id: "uuid.UUID"

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        # RelatedObjectDoesNotExist subclasses AttributeError, so an unset pipeline reads as None.
        pipeline = getattr(self, "pipeline", None)
        if pipeline is not None:
            # Overwrite unconditionally: an explicit team_id that disagrees with the
            # pipeline's would file the row under the wrong tenant.
            self.team_id = pipeline.team_id
            # A partial save that writes the pipeline must write the derived team with it,
            # or the row keeps its old tenant while pointing at the new pipeline.
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and not {"pipeline", "pipeline_id"}.isdisjoint(update_fields):
                kwargs["update_fields"] = {*update_fields, "team"}
        for relation_name in self._pipeline_bound_relations:
            related = getattr(self, relation_name, None)
            if related is not None and related.pipeline_id != self.pipeline_id:
                raise ValueError(
                    f"{type(self).__name__}.{relation_name} belongs to pipeline {related.pipeline_id}, "
                    f"not this row's pipeline {self.pipeline_id}"
                )
        super().save(*args, **kwargs)


class AutoresearchModel(PipelineScopedModel):
    """A persisted, versioned champion or challenger recipe."""

    class Role(models.TextChoices):
        CHAMPION = "champion", "Champion"
        CHALLENGER = "challenger", "Challenger"
        ARCHIVED = "archived", "Archived"

    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="models")

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CHALLENGER)

    _pipeline_bound_relations = ("source_training_run",)

    # Portable recipe, the load-bearing artifact
    recipe_hash = models.CharField(max_length=64, help_text="SHA-256 of the serialized recipe JSON")
    model_recipe = models.JSONField(
        help_text="Portable recipe: feature_sql, feature_transforms, model_class, model_params, etc."
    )
    # Object-storage key prefix for the artifact bundle (train.py, predict.py, features.sql).
    # When set, inference runs the bundle in a sandbox instead of the in-process recipe path.
    # Empty for legacy recipe-only models.
    artifact_prefix = models.CharField(max_length=500, blank=True, default="")
    model_explanation = models.JSONField(
        default=dict,
        help_text="Global feature importance, directionality, stability, leakage warnings",
    )

    # Performance
    holdout_score = models.FloatField(
        null=True, blank=True, validators=UNIT_INTERVAL_VALIDATORS, help_text="Offline holdout AUC"
    )
    realized_score = models.FloatField(
        null=True,
        blank=True,
        validators=UNIT_INTERVAL_VALIDATORS,
        help_text="Online realized AUC once labels mature",
    )
    calibration_error = models.FloatField(null=True, blank=True)
    metrics = models.JSONField(default=dict, help_text="Full metrics bundle (train/holdout/realized)")

    # Provenance
    source_training_run = models.ForeignKey(
        "autoresearch.AutoresearchTrainingRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="candidate_models",
    )
    agent_description = models.TextField(blank=True, default="")
    trained_on_start = models.DateField(null=True, blank=True)
    trained_on_end = models.DateField(null=True, blank=True)
    is_preliminary = models.BooleanField(
        default=True, help_text="True until at least one realized validation cycle completes"
    )

    promoted_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        default_manager_name = "all_teams"
        constraints = [
            # Inference and scoring read "the champion" as a single row; two champions
            # would make that read ambiguous, so the database rejects the second.
            models.UniqueConstraint(
                fields=["pipeline"],
                condition=models.Q(role="champion"),
                name="autoresearch_one_champion_per_pipeline",
            ),
            unit_interval_constraint("holdout_score", "autoresearch_model_holdout_score_in_unit_range"),
            unit_interval_constraint("realized_score", "autoresearch_model_realized_score_in_unit_range"),
            models.CheckConstraint(
                check=models.Q(trained_on_start__isnull=True)
                | models.Q(trained_on_end__isnull=True)
                | models.Q(trained_on_start__lte=models.F("trained_on_end")),
                name="autoresearch_model_trained_on_range_ordered",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.role} model for pipeline {self.pipeline_id}"


class AutoresearchTrainingRun(PipelineScopedModel):
    """One bounded training/bootstrap session backed by a Task/TaskRun."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="training_runs")

    # Link to the Task/TaskRun sandbox (nullable for stubs).
    # task_id is the parent Task, which the /tasks/:taskId detail UI needs.
    # task_run_id is the specific TaskRun, kept for log lookups.
    task_id = models.UUIDField(null=True, blank=True, help_text="Parent Task ID in the tasks product sandbox")
    task_run_id = models.UUIDField(null=True, blank=True, help_text="TaskRun ID in the tasks product sandbox")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    iteration_budget = models.IntegerField(default=50, validators=[MinValueValidator(1)])
    iteration_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    best_holdout_score = models.FloatField(null=True, blank=True, validators=UNIT_INTERVAL_VALIDATORS)
    error = models.TextField(blank=True, default="")
    # Tier-1 cross-run learning memory: a distilled, structured summary of this run written on
    # completion. Backend derives the structural fields (champion, kept ladder, dead-ends) from the
    # recorded iterations; the agent enriches recommended_next + distillation via the complete tool.
    # Read back by a new run via the training_runs/history endpoint to orient before iterating.
    summary = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        default_manager_name = "all_teams"
        constraints = [
            unit_interval_constraint(
                "best_holdout_score", "autoresearch_training_run_best_holdout_score_in_unit_range"
            ),
            min_value_constraint("iteration_budget", 1, "autoresearch_training_run_iteration_budget_positive"),
            min_value_constraint("iteration_count", 0, "autoresearch_training_run_iteration_count_nonnegative"),
        ]


class AutoresearchIteration(PipelineScopedModel):
    """One recipe attempt within a training run."""

    class Status(models.TextChoices):
        KEPT = "kept", "Kept"
        DISCARDED = "discarded", "Discarded"
        CRASHED = "crashed", "Crashed"

    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="iterations")
    training_run = models.ForeignKey(AutoresearchTrainingRun, on_delete=models.CASCADE, related_name="iterations")

    _pipeline_bound_relations = ("training_run", "parent_suggestion")

    iteration_number = models.IntegerField()
    recipe_hash = models.CharField(max_length=64)
    recipe_snapshot = models.JSONField(help_text="Compact recipe at time of iteration; full artifact in model row")
    model_spec = models.JSONField(default=dict, help_text="model_class + hyperparams tried this iteration")

    train_score = models.FloatField(null=True, blank=True, validators=UNIT_INTERVAL_VALIDATORS)
    holdout_score = models.FloatField(null=True, blank=True, validators=UNIT_INTERVAL_VALIDATORS)
    status = models.CharField(max_length=20, choices=Status.choices)
    agent_description = models.TextField(blank=True, default="")
    agent_confidence = models.FloatField(
        null=True, blank=True, validators=UNIT_INTERVAL_VALIDATORS, help_text="Agent's self-assessed confidence 0–1"
    )
    parent_suggestion = models.ForeignKey(
        "autoresearch.AutoresearchSuggestion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="iterations",
        help_text="Suggestion that spawned this iteration, if any",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["iteration_number"]
        default_manager_name = "all_teams"
        unique_together = [("training_run", "iteration_number")]
        constraints = [
            unit_interval_constraint("train_score", "autoresearch_iteration_train_score_in_unit_range"),
            unit_interval_constraint("holdout_score", "autoresearch_iteration_holdout_score_in_unit_range"),
            unit_interval_constraint("agent_confidence", "autoresearch_iteration_agent_confidence_in_unit_range"),
        ]


class AutoresearchSuggestion(PipelineScopedModel):
    """A free-text hypothesis or direction injected into a running pipeline by a user or agent."""

    class Priority(models.TextChoices):
        TRY_NEXT = "try_next", "Try next"
        CONSIDER = "consider", "Consider"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PICKED_UP = "picked_up", "Picked up"
        ACTED_ON = "acted_on", "Acted on"
        DISMISSED = "dismissed", "Dismissed"

    class Source(models.TextChoices):
        USER = "user", "User"
        AGENT = "agent", "Agent"

    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="suggestions")
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=False,
        db_constraint=False,
        related_name="+",
    )

    prompt = models.TextField(help_text="Free-text hypothesis or direction for the agent to explore")
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.CONSIDER,
        help_text="'try_next' instructs the agent to act on this before other iterations; 'consider' is advisory",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.USER,
        help_text="Whether the suggestion came from a human user or an agent",
    )
    agent_response = models.TextField(
        blank=True,
        default="",
        help_text="Agent's note on how the suggestion was interpreted and acted upon",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        default_manager_name = "all_teams"

    def __str__(self) -> str:
        return f"[{self.priority}] {self.prompt[:60]} ({self.status})"


class AutoresearchRun(PipelineScopedModel):
    """Generic operational run: inference or validation."""

    class RunType(models.TextChoices):
        INFERENCE = "inference", "Inference"
        VALIDATION = "validation", "Validation"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="runs")

    _pipeline_bound_relations = ("model",)

    model = models.ForeignKey(
        AutoresearchModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
        help_text="Champion model used for this run",
    )
    run_type = models.CharField(max_length=20, choices=RunType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    rows_scored = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    metrics = models.JSONField(default=dict)
    error = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        default_manager_name = "all_teams"
        constraints = [
            min_value_constraint("rows_scored", 0, "autoresearch_run_rows_scored_nonnegative", nullable=True),
        ]
