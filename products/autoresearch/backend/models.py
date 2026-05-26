from django.db import models

from posthog.models.utils import UUIDModel, uuid7


class AutoresearchPipeline(UUIDModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BOOTSTRAPPING = "bootstrapping", "Bootstrapping"
        RUNNING = "running", "Running"
        CONVERGED = "converged", "Converged"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    class PredictionMode(models.TextChoices):
        ADOPTION = "adoption", "Adoption"
        CONTINUATION = "continuation", "Continuation"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="autoresearch_pipelines")
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_index=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    # Prediction target
    target_event = models.CharField(max_length=255, help_text="Event name to predict, e.g. '$pageview'")
    target_definition = models.JSONField(
        default=dict, help_text="Full target definition including filters and positive-label logic"
    )
    horizon_days = models.IntegerField(default=7, help_text="Predict whether the target occurs within N days")
    prediction_mode = models.CharField(
        max_length=20,
        choices=PredictionMode.choices,
        default=PredictionMode.ADOPTION,
        help_text="Adoption: users who have not done the target yet. Continuation: users who have.",
    )

    # Population
    training_population = models.JSONField(
        default=dict, help_text="HogQL cohort or filter defining the training population"
    )
    inference_population = models.JSONField(
        default=dict, help_text="HogQL cohort or filter defining the daily scoring population"
    )

    # Schedule and budget
    cadence_days = models.IntegerField(default=1, help_text="Re-score every N days")
    iteration_budget = models.IntegerField(default=50, help_text="Max training iterations for the autoresearch loop")
    iteration_budget_remaining = models.IntegerField(default=50)

    # Stop criteria
    success_auc = models.FloatField(null=True, blank=True, help_text="Stop when holdout AUC reaches this threshold")
    plateau_iterations = models.IntegerField(
        default=10, help_text="Stop if no improvement after this many consecutive iterations"
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

    def __str__(self) -> str:
        return f"{self.name} ({self.team_id})"


class AutoresearchModel(UUIDModel):
    """A persisted, versioned champion or challenger recipe."""

    class Role(models.TextChoices):
        CHAMPION = "champion", "Champion"
        CHALLENGER = "challenger", "Challenger"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="models")

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CHALLENGER)

    # Portable recipe — the load-bearing artifact
    recipe_hash = models.CharField(max_length=64, help_text="SHA-256 of the serialized recipe JSON")
    model_recipe = models.JSONField(
        help_text="Portable recipe: feature_sql, feature_transforms, model_class, model_params, etc."
    )
    model_explanation = models.JSONField(
        default=dict,
        help_text="Global feature importance, directionality, stability, leakage warnings",
    )

    # Performance
    holdout_score = models.FloatField(null=True, blank=True, help_text="Offline holdout AUC")
    realized_score = models.FloatField(null=True, blank=True, help_text="Online realized AUC once labels mature")
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

    def __str__(self) -> str:
        return f"{self.role} model for pipeline {self.pipeline_id}"


class AutoresearchTrainingRun(UUIDModel):
    """One bounded training/bootstrap session backed by a Task/TaskRun."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="training_runs")

    # Link to the Task/TaskRun sandbox (nullable for stubs)
    task_run_id = models.UUIDField(null=True, blank=True, help_text="TaskRun ID in the tasks product sandbox")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    iteration_budget = models.IntegerField(default=50)
    iteration_count = models.IntegerField(default=0)
    best_holdout_score = models.FloatField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AutoresearchIteration(UUIDModel):
    """One recipe attempt within a training run."""

    class Status(models.TextChoices):
        KEPT = "kept", "Kept"
        DISCARDED = "discarded", "Discarded"
        CRASHED = "crashed", "Crashed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="iterations")
    training_run = models.ForeignKey(AutoresearchTrainingRun, on_delete=models.CASCADE, related_name="iterations")
    parent_iteration = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )

    iteration_number = models.IntegerField()
    recipe_hash = models.CharField(max_length=64)
    recipe_snapshot = models.JSONField(help_text="Compact recipe at time of iteration; full artifact in model row")
    model_spec = models.JSONField(default=dict, help_text="model_class + hyperparams tried this iteration")

    train_score = models.FloatField(null=True, blank=True)
    holdout_score = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    agent_description = models.TextField(blank=True, default="")
    agent_confidence = models.FloatField(null=True, blank=True, help_text="Agent's self-assessed confidence 0–1")
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
        unique_together = [("training_run", "iteration_number")]


class AutoresearchSuggestion(UUIDModel):
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

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="suggestions")
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_index=False)

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

    def __str__(self) -> str:
        return f"[{self.priority}] {self.prompt[:60]} ({self.status})"


class AutoresearchRun(UUIDModel):
    """Generic operational run: inference, validation, or notebook generation."""

    class RunType(models.TextChoices):
        INFERENCE = "inference", "Inference"
        VALIDATION = "validation", "Validation"
        NOTEBOOK = "notebook", "Notebook"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    pipeline = models.ForeignKey(AutoresearchPipeline, on_delete=models.CASCADE, related_name="runs")
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

    rows_scored = models.IntegerField(null=True, blank=True)
    metrics = models.JSONField(default=dict)
    error = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
