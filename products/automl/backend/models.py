"""
Django models for AutoML.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py for choices where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import AutonomyLevel, Cadence, ModelRole, PipelineStatus, TaskType


class AutoMLPipeline(ProductTeamModel):
    """A user-configured AutoML pipeline.

    Stores the durable config plus high-level status. Task-type-specific
    config lives in ``config`` as JSON for now; the IO contract in the
    ``automl`` design skill (``io-spec.md``) describes the per-task shape.
    We may break out typed columns once the contract is exercised.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    name = models.CharField(
        max_length=255,
        help_text="Human-readable pipeline name. Unique within the team.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Free-form description for the pipeline detail page.",
    )

    task_type = models.CharField(
        max_length=32,
        choices=[(t.value, t.value) for t in TaskType],
        help_text="One of clustering / classification / regression / forecasting.",
    )
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in PipelineStatus],
        default=PipelineStatus.DRAFT.value,
        help_text="Lifecycle state of the pipeline.",
    )
    autonomy = models.CharField(
        max_length=32,
        choices=[(a.value, a.value) for a in AutonomyLevel],
        default=AutonomyLevel.CHAMPION_ONLY.value,
        help_text="Output autonomy gate: shadow_only / champion_only / promote_eligible.",
    )

    config = models.JSONField(
        default=dict,
        help_text="Task-type-specific configuration (target, horizon, cluster_count, etc.).",
    )
    training_population = models.JSONField(
        default=dict,
        help_text='Population definition for training, e.g. {"kind": "hogql", "query": "..."}.',
    )
    inference_population = models.JSONField(
        default=dict,
        help_text="Population definition for scheduled inference.",
    )

    inference_cadence = models.CharField(
        max_length=16,
        choices=[(c.value, c.value) for c in Cadence],
        default=Cadence.DAILY.value,
        help_text="How often the inference workflow runs.",
    )
    retraining_cadence = models.CharField(
        max_length=16,
        choices=[(c.value, c.value) for c in Cadence],
        default=Cadence.DAILY.value,
        help_text="How often the model is refit on a rolling window.",
    )

    output_property_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Person/group property name to write the latest prediction to.",
    )

    runtime = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "System-managed runtime state. Holds pointers like the bootstrap task id, "
            "the bootstrap error message, and the last inference timestamp. Model "
            "version pointers (champion / challenger) live on `AutoMLModelVersion.role` "
            "instead. Distinct from user-configured `config` so we never overwrite "
            "user intent with system state."
        ),
    )

    # Plain integer instead of FK — keeps us free to move products to separate
    # databases later without rewriting (per products/architecture.md).
    created_by_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="ID of the user who created the pipeline.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "name"],
                name="automl_pipeline_team_name_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "status"]),
            models.Index(fields=["team_id", "task_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.task_type})"


class AutoMLModelVersion(ProductTeamModel):
    """A single trained model version on an AutoML pipeline.

    Each training run inside the sandbox produces one row. The row is the
    durable record of *what was trained* — metrics, leaderboard, training
    parameters, problem type. The actual model artifact lives in object
    storage and is pointed at by ``artifact_uri``.

    ``role`` tracks the version's lifecycle (champion / challenger /
    archived). The partial unique constraint enforces at most one champion
    and at most one challenger per pipeline at any time. Promotion is an
    atomic two-step: archive the current champion, then mark the new model
    as champion.

    The ``id`` lands on every emitted prediction as ``$model_version_id``
    (per ``io-spec.md`` in the ``/phs automl`` skill), so it's a stable
    provenance handle across the pipeline → training → inference →
    prediction chain.

    ``tracking_metadata`` is a flex hatch for future linkage to external
    experiment trackers (MLflow, W&B, an internal tracking server). Empty
    today; adding a tracker doesn't require a migration.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    pipeline = models.ForeignKey(
        AutoMLPipeline,
        on_delete=models.CASCADE,
        # No reverse manager — callers go through the facade so the join
        # direction stays explicit (and so this product can move to a
        # separate database later without rewriting consumers).
        related_name="+",
        help_text="The pipeline this model version belongs to.",
    )
    role = models.CharField(
        max_length=16,
        choices=[(r.value, r.value) for r in ModelRole],
        default=ModelRole.CHALLENGER.value,
        help_text=(
            "Lifecycle role: champion (serves traffic), challenger (head-to-head, "
            "event-only), archived (audit-only). At most one champion and one "
            "challenger per pipeline."
        ),
    )

    metrics = models.JSONField(
        default=dict,
        blank=True,
        help_text="Scalar metrics dict, e.g. {'roc_auc': 0.85, 'log_loss': 0.42}.",
    )
    leaderboard = models.JSONField(
        default=list,
        blank=True,
        help_text="AutoGluon leaderboard records (top-N models). One JSON object per model.",
    )
    training_params = models.JSONField(
        default=dict,
        blank=True,
        help_text="Training hyper-parameters (seed, presets, time_limit_s, val_fraction, test_fraction, ...).",
    )
    tracking_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Flex hatch for external experiment-tracker linkage (mlflow_run_id, "
            "wandb_run_id, etc.). Empty today; written if/when a tracking server "
            "lands. Schemaless on purpose so we can add trackers without migration."
        ),
    )

    eval_metric = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="AutoGluon eval metric name, e.g. 'roc_auc', 'rmse'.",
    )
    problem_type = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="AutoGluon problem type: 'binary', 'multiclass', 'regression', etc.",
    )
    artifact_uri = models.TextField(
        blank=True,
        default="",
        help_text=(
            "URI of the serialized model artifact. Empty when the producer has no "
            "durable storage (e.g. sandbox runs before S3 wiring lands). Schemes vary "
            "by producer (file://, s3://, ...) — load-side decides how to resolve."
        ),
    )
    features_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Hash of the training feature set. Matches `$features_hash` on emitted predictions.",
    )

    rows_train = models.IntegerField(
        null=True,
        blank=True,
        help_text="Rows in the training split (provenance).",
    )
    rows_val = models.IntegerField(
        null=True,
        blank=True,
        help_text="Rows in the validation split (provenance).",
    )
    rows_test = models.IntegerField(
        null=True,
        blank=True,
        help_text="Rows in the held-out test split (provenance).",
    )

    training_task_id = models.UUIDField(
        null=True,
        blank=True,
        help_text=(
            "Back-reference to the ``tasks.Task`` row that produced this version. "
            "Plain UUID instead of FK — keeps us free to move products to separate "
            "databases later (per products/architecture.md)."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            # Partial unique: enforces at-most-one champion + at-most-one challenger
            # per pipeline. Archived rows are unconstrained so history can stack.
            models.UniqueConstraint(
                fields=["pipeline", "role"],
                condition=models.Q(role__in=[ModelRole.CHAMPION.value, ModelRole.CHALLENGER.value]),
                name="automl_one_active_role_per_pipeline",
            ),
        ]
        indexes = [
            # Listing model versions for a pipeline (newest first) is the hot path.
            models.Index(fields=["team_id", "pipeline", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.id} ({self.role})"
