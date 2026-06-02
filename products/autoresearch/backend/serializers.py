from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.recipe_validation import RecipeValidationError, validate_recipe

# ── Typed schema wrappers for JSONField -----------------------------------


@extend_schema_field(
    {
        "type": "object",
        "description": "Full target definition. May include event filters, action IDs, and positive-label conditions.",
        "example": {"event": "$pageview", "filters": []},
    }
)
class TargetDefinitionField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "description": "Population definition as a HogQL cohort or filter object. Use {} for 'all identified users'.",
        "example": {"properties": [{"key": "email", "type": "person", "operator": "is_set"}]},
    }
)
class PopulationDefinitionField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Portable recipe artifact. Contains feature_sql (HogQL), feature_transforms, "
            "model_class, model_params, fit_signature, trained_on, holdout_score, and agent_description."
        ),
        "example": {
            "feature_sql": "SELECT distinct_id, countIf(event='$pageview') AS pageviews_30d FROM events ...",
            "feature_transforms": [],
            "model_class": "sklearn.linear_model.LogisticRegression",
            "model_params": {"C": 1.0, "max_iter": 200},
            "fit_signature": "abc123",
            "trained_on": "2026-04-01 to 2026-05-01",
            "holdout_score": 0.72,
            "agent_description": "Stub recipe: universal engagement features",
        },
    }
)
class ModelRecipeField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Global feature importance bundle: top features by gain, directionality "
            "(positive/negative impact on predicted probability), stability across runs, "
            "and leakage warning annotations."
        ),
    }
)
class ModelExplanationField(serializers.JSONField):
    pass


# ── Core serializers ------------------------------------------------------


class AutoresearchPipelineSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    target_definition = TargetDefinitionField(
        help_text="Full target definition including event filters and positive-label conditions."
    )
    training_population = PopulationDefinitionField(
        help_text="Population used for training. Defines which users can appear as training examples."
    )
    inference_population = PopulationDefinitionField(
        help_text="Population scored daily. Typically broader than the training population."
    )
    champion_holdout_auc = serializers.SerializerMethodField(
        help_text="Offline holdout AUC of the current champion model (predictive accuracy on held-out training data)."
    )
    champion_realized_auc = serializers.SerializerMethodField(
        help_text="Realized online AUC of the current champion model, computed from mature predictions against actual outcomes."
    )

    def get_champion_holdout_auc(self, obj: AutoresearchPipeline) -> float | None:
        champion = obj.models.filter(role="champion").only("holdout_score").order_by("-created_at").first()
        return champion.holdout_score if champion else None

    def get_champion_realized_auc(self, obj: AutoresearchPipeline) -> float | None:
        champion = obj.models.filter(role="champion").only("realized_score").order_by("-created_at").first()
        return champion.realized_score if champion else None

    class Meta:
        model = AutoresearchPipeline
        fields = [
            "id",
            "name",
            "description",
            "target_event",
            "target_definition",
            "horizon_days",
            "training_lookback_days",
            "training_population",
            "inference_population",
            "cadence_days",
            "iteration_budget",
            "iteration_budget_remaining",
            "success_auc",
            "plateau_iterations",
            "output_person_property",
            "status",
            "created_by",
            "created_at",
            "updated_at",
            "last_scored_at",
            "champion_holdout_auc",
            "champion_realized_auc",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "last_scored_at",
            "iteration_budget_remaining",
            "status",
            "champion_holdout_auc",
            "champion_realized_auc",
        ]
        extra_kwargs = {
            "id": {"help_text": "Unique UUID of this pipeline."},
            "name": {"help_text": "Display name for the pipeline."},
            "description": {"help_text": "Optional free-text description."},
            "target_event": {"help_text": "PostHog event name to predict, e.g. '$pageview' or 'signed_up'."},
            "horizon_days": {
                "help_text": "Prediction horizon in days. The model predicts whether the target event occurs within this window."
            },
            "training_lookback_days": {
                "help_text": "How far back to look for training examples. Larger windows give more data but may include stale behavior."
            },
            "cadence_days": {"help_text": "Re-score the inference population every N days."},
            "iteration_budget": {"help_text": "Total training iterations allowed for the autoresearch loop."},
            "iteration_budget_remaining": {"help_text": "Iterations remaining in the current budget."},
            "success_auc": {"help_text": "Target AUC threshold. Training stops early if this score is reached."},
            "plateau_iterations": {
                "help_text": "Stop training if no AUC improvement is seen in this many consecutive iterations."
            },
            "output_person_property": {
                "help_text": "Person property name that stores the daily prediction score, e.g. 'predicted_p_pageview'."
            },
            "status": {
                "help_text": "Pipeline lifecycle status: draft, bootstrapping, running, converged, paused, or archived."
            },
            "last_scored_at": {"help_text": "Timestamp of the most recent completed inference run."},
        }


class AutoresearchPipelineCreateSerializer(serializers.ModelSerializer):
    target_definition = TargetDefinitionField(
        required=False,
        default=dict,
        help_text="Full target definition. Can be left empty to use target_event alone.",
    )
    training_population = PopulationDefinitionField(
        required=False,
        default=dict,
        help_text="Training population filter. Use {} for all identified users.",
    )
    inference_population = PopulationDefinitionField(
        required=False,
        default=dict,
        help_text="Inference population filter. Defaults to training_population if not set.",
    )

    class Meta:
        model = AutoresearchPipeline
        fields = [
            "name",
            "description",
            "target_event",
            "target_definition",
            "horizon_days",
            "training_lookback_days",
            "training_population",
            "inference_population",
            "cadence_days",
            "iteration_budget",
            "success_auc",
            "plateau_iterations",
            "output_person_property",
        ]
        extra_kwargs = {
            "name": {"help_text": "Display name for the pipeline."},
            "description": {"help_text": "Optional free-text description."},
            "target_event": {"help_text": "PostHog event name to predict, e.g. '$pageview' or 'signed_up'."},
            "horizon_days": {
                "help_text": "Prediction horizon in days. The model predicts whether the target event occurs within this window."
            },
            "training_lookback_days": {
                "help_text": "How far back to look for training examples. Larger windows give more data but may include stale behavior. Default: 180."
            },
            "cadence_days": {"help_text": "Re-score the inference population every N days. Default: 1."},
            "iteration_budget": {
                "help_text": "Total training iterations allowed for the autoresearch loop. Default: 50."
            },
            "success_auc": {"help_text": "Target AUC threshold. Training stops early if reached. Default: 0.75."},
            "plateau_iterations": {
                "help_text": "Stop training if no improvement in this many consecutive iterations. Default: 10."
            },
            "output_person_property": {
                "help_text": "Person property name for the prediction score. Auto-derived from target_event if omitted, e.g. 'predicted_p_pageview'."
            },
        }

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if not data.get("output_person_property"):
            safe_name = data.get("target_event", "target").lstrip("$").replace(" ", "_").lower()
            # Include the horizon so two pipelines predicting the same target over different
            # horizons don't $set the same person property and clobber each other's scores.
            horizon = data.get("horizon_days") or 7
            data["output_person_property"] = f"predicted_p_{safe_name}_{horizon}d"
        if not data.get("inference_population"):
            data["inference_population"] = data.get("training_population", {})
        return data


class AutoresearchModelSerializer(serializers.ModelSerializer):
    model_recipe = ModelRecipeField(
        help_text="Portable recipe artifact. Feature SQL, transforms, model class, params, and metadata."
    )
    model_explanation = ModelExplanationField(
        help_text="Global feature importance and directionality. Used to explain top drivers on the model card."
    )

    class Meta:
        model = AutoresearchModel
        fields = [
            "id",
            "pipeline",
            "role",
            "recipe_hash",
            "model_recipe",
            "model_explanation",
            "holdout_score",
            "realized_score",
            "calibration_error",
            "metrics",
            "agent_description",
            "trained_on_start",
            "trained_on_end",
            "is_preliminary",
            "promoted_at",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "recipe_hash", "created_at", "updated_at"]
        extra_kwargs = {
            "id": {"help_text": "Unique UUID of this model version."},
            "pipeline": {"help_text": "Pipeline this model belongs to."},
            "role": {
                "help_text": "Model role: 'champion' (active scoring model), 'challenger' (shadow model), or 'archived'."
            },
            "recipe_hash": {
                "help_text": "SHA-256 of the serialized recipe. Used to deduplicate identical recipes across runs."
            },
            "holdout_score": {
                "help_text": "AUC on the held-out test split at training time. Preliminary signal before online labels mature."
            },
            "realized_score": {
                "help_text": "Online AUC computed from actual realized outcomes. Authoritative once enough labels have matured."
            },
            "calibration_error": {
                "help_text": "Expected calibration error (ECE). Lower is better; well-calibrated models have ECE < 0.05."
            },
            "metrics": {
                "help_text": "Extended metrics bundle: Brier score, precision/recall at thresholds, lift@k, base rate, row counts."
            },
            "agent_description": {
                "help_text": "The agent's own plain-English description of what this recipe does and why it was chosen."
            },
            "trained_on_start": {"help_text": "Start of the training data window (inclusive)."},
            "trained_on_end": {"help_text": "End of the training data window (exclusive)."},
            "is_preliminary": {
                "help_text": "True if this model has not yet been validated against realized online outcomes."
            },
            "promoted_at": {"help_text": "Timestamp when this model was promoted to champion."},
            "archived_at": {"help_text": "Timestamp when this model was archived (superseded or retired)."},
        }


class TrainingRunSummaryLadderItemSerializer(serializers.Serializer):
    """One iteration referenced from a run summary's ladder or dead-ends list."""

    iteration_number = serializers.IntegerField(help_text="Iteration index this entry refers to.")
    holdout_score = serializers.FloatField(allow_null=True, help_text="Holdout AUC for this iteration.")
    model_class = serializers.CharField(allow_blank=True, help_text="Model class tried in this iteration.")
    agent_description = serializers.CharField(allow_blank=True, help_text="The agent's rationale for this attempt.")


class TrainingRunSummarySerializer(serializers.Serializer):
    """Tier-1 distilled summary of a completed run — the orientation memory a new run reads first."""

    target_event = serializers.CharField(help_text="Target event the run's pipeline predicts.")
    horizon_days = serializers.IntegerField(help_text="Prediction horizon, in days.")
    best_holdout_score = serializers.FloatField(allow_null=True, help_text="Best holdout AUC achieved in the run.")
    champion_promoted = serializers.BooleanField(
        help_text="Whether this run's best model was promoted to champion (vs kept as challenger)."
    )
    champion_model_class = serializers.CharField(allow_blank=True, help_text="Model class of the run's best model.")
    kept_ladder = TrainingRunSummaryLadderItemSerializer(
        many=True,
        help_text="Kept iterations, highest holdout AUC first — the winning approaches worth reusing.",
    )
    dead_ends = TrainingRunSummaryLadderItemSerializer(
        many=True,
        help_text="Discarded or crashed iterations — approaches already tried that did not help; avoid repeating.",
    )
    recommended_next = serializers.CharField(
        allow_blank=True, help_text="Agent's suggested next experiments for a future run. Empty if not provided."
    )
    distillation = serializers.CharField(
        allow_blank=True, help_text="Agent's 1–2 sentence distillation of what this run learned. Empty if not provided."
    )


class AutoresearchTrainingRunSerializer(serializers.ModelSerializer):
    task_url = serializers.SerializerMethodField(
        help_text="Relative URL to the underlying sandbox Task detail page. Null for stub/synchronous training runs."
    )
    summary = serializers.SerializerMethodField(
        help_text="Distilled cross-run learning summary written on completion. Null until the run completes."
    )

    class Meta:
        model = AutoresearchTrainingRun
        fields = [
            "id",
            "pipeline",
            "task_id",
            "task_run_id",
            "task_url",
            "status",
            "iteration_budget",
            "iteration_count",
            "best_holdout_score",
            "summary",
            "error",
            "started_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "task_url",
            "status",
            "iteration_count",
            "best_holdout_score",
            "summary",
            "error",
            "started_at",
            "completed_at",
            "created_at",
        ]
        extra_kwargs = {
            "id": {"help_text": "Unique UUID of this training run."},
            "pipeline": {"help_text": "Pipeline this training run belongs to."},
            "task_id": {"help_text": "Parent Task ID in the tasks sandbox. Null for stub runs."},
            "task_run_id": {"help_text": "Task sandbox run ID. Null for stub/synchronous training runs."},
            "status": {"help_text": "Run status: pending, running, completed, or failed."},
            "iteration_budget": {"help_text": "Maximum iterations allowed for this run."},
            "iteration_count": {"help_text": "Number of iterations completed."},
            "best_holdout_score": {"help_text": "Best holdout AUC achieved across all iterations in this run."},
            "error": {"help_text": "Error message if the run failed."},
            "started_at": {"help_text": "Timestamp when the training run started."},
            "completed_at": {"help_text": "Timestamp when the training run completed or failed."},
        }

    def get_task_url(self, obj: AutoresearchTrainingRun) -> str | None:
        return f"/tasks/{obj.task_id}" if obj.task_id else None

    @extend_schema_field(TrainingRunSummarySerializer(allow_null=True))
    def get_summary(self, obj: AutoresearchTrainingRun) -> dict[str, Any] | None:
        return obj.summary or None


class AutoresearchIterationSerializer(serializers.ModelSerializer):
    recipe_snapshot = serializers.JSONField(
        help_text="Compact recipe snapshot at time of iteration. Full artifact lives in the model row."
    )
    model_spec = serializers.JSONField(help_text="Model class and hyperparameters tried in this iteration.")

    class Meta:
        model = AutoresearchIteration
        fields = [
            "id",
            "pipeline",
            "training_run",
            "parent_iteration",
            "iteration_number",
            "recipe_hash",
            "recipe_snapshot",
            "model_spec",
            "train_score",
            "holdout_score",
            "status",
            "agent_description",
            "agent_confidence",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class IterationTrailSerializer(serializers.ModelSerializer):
    """Compact, read-only view of one iteration for the cross-run history feed."""

    model_spec = serializers.JSONField(help_text="Model class and hyperparameters tried in this iteration.")

    class Meta:
        model = AutoresearchIteration
        fields = [
            "iteration_number",
            "status",
            "holdout_score",
            "train_score",
            "agent_description",
            "model_spec",
        ]
        extra_kwargs = {
            "iteration_number": {"help_text": "Order of this attempt within its run (0-based)."},
            "status": {"help_text": "Whether this recipe was kept (improved the best score), discarded, or crashed."},
            "holdout_score": {"help_text": "Holdout AUC this iteration achieved. Null if it was skipped/degenerate."},
            "train_score": {"help_text": "Train-fold AUC for this iteration, if recorded."},
            "agent_description": {"help_text": "The agent's one-line rationale for what it tried and why."},
        }


class TrainingRunHistoryEntrySerializer(serializers.Serializer):
    """One prior completed training run plus its full iteration trail."""

    run_id = serializers.UUIDField(help_text="UUID of the completed training run.")
    pipeline_id = serializers.UUIDField(help_text="UUID of the pipeline this run belongs to.")
    is_current_pipeline = serializers.BooleanField(
        help_text=(
            "True if this run is from the pipeline you are training; False if it is a same-target "
            "sibling pipeline on the team."
        )
    )
    target_event = serializers.CharField(help_text="Target event this run's pipeline predicts.")
    horizon_days = serializers.IntegerField(help_text="Prediction horizon (days) of this run's pipeline.")
    best_holdout_score = serializers.FloatField(
        allow_null=True, help_text="Best holdout AUC achieved across this run's iterations."
    )
    iteration_count = serializers.IntegerField(help_text="Number of iterations recorded in this run.")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="When this run completed.")
    summary = TrainingRunSummarySerializer(
        allow_null=True,
        help_text="Distilled tier-1 summary of this run — read this first to orient. Null for older runs without one.",
    )
    iterations = IterationTrailSerializer(
        many=True,
        help_text="The iteration trail: every recipe tried, kept or discarded, with rationale and score.",
    )


class TrainingRunHistorySerializer(serializers.Serializer):
    """Cross-run learning memory: prior runs the agent should read before iterating."""

    runs = TrainingRunHistoryEntrySerializer(
        many=True,
        help_text=(
            "Recent completed training runs — the current pipeline first, then same-target sibling "
            "pipelines on the team — newest first. Mine these to reuse winning features and avoid "
            "repeating discarded approaches."
        ),
    )


class AutoresearchRunSerializer(serializers.ModelSerializer):
    metrics = serializers.JSONField(
        help_text="Run metrics: rows scored, score distribution summary, validation AUC, etc."
    )

    class Meta:
        model = AutoresearchRun
        fields = [
            "id",
            "pipeline",
            "model",
            "run_type",
            "status",
            "rows_scored",
            "metrics",
            "error",
            "started_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {
            "id": {"help_text": "Unique UUID of this run."},
            "pipeline": {"help_text": "Pipeline this run belongs to."},
            "model": {"help_text": "Model used for scoring. Null for validation or notebook runs."},
            "run_type": {
                "help_text": "Type of run: 'inference' (daily scoring), 'validation' (outcome evaluation), or 'notebook' (report generation)."
            },
            "status": {"help_text": "Run status: pending, running, completed, or failed."},
            "rows_scored": {"help_text": "Number of users scored in this inference run."},
            "error": {"help_text": "Error message if the run failed."},
            "started_at": {"help_text": "Timestamp when the run started."},
            "completed_at": {"help_text": "Timestamp when the run completed or failed."},
        }


# ── Validation serializers -------------------------------------------------


class ValidationWarningSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Machine-readable warning code, e.g. 'low_volume' or 'extreme_imbalance'.")
    message = serializers.CharField(help_text="Human-readable warning description.")
    severity = serializers.ChoiceField(
        choices=["info", "warning", "error"],
        help_text="Severity level. 'error' blocks creation; 'warning' requires acknowledgement.",
    )


class ValidatePipelineRequestSerializer(serializers.Serializer):
    target_event = serializers.CharField(
        help_text="Event name to predict, e.g. '$pageview'. Must exist in the team's event schema.",
    )
    horizon_days = serializers.IntegerField(
        default=7,
        min_value=1,
        max_value=365,
        help_text="Predict whether the target event occurs within this many days.",
    )
    training_lookback_days = serializers.IntegerField(
        default=180,
        min_value=7,
        max_value=730,
        help_text="How far back to look for training examples. Default: 180.",
    )
    training_population = serializers.JSONField(
        default=dict,
        help_text="Population filter for training examples. Use {} for all identified users.",
    )
    inference_population = serializers.JSONField(
        default=dict,
        help_text="Population filter for daily scoring. Defaults to training_population if not provided.",
    )


class ValidatePipelineResponseSerializer(serializers.Serializer):
    can_proceed = serializers.BooleanField(help_text="True if the pipeline definition is valid and training can start.")
    requires_acknowledgement = serializers.BooleanField(
        help_text="True if there are non-blocking warnings the user should acknowledge before proceeding."
    )
    estimated_training_rows = serializers.IntegerField(
        allow_null=True,
        help_text="Estimated number of user-level training rows based on the population and lookback window.",
    )
    positive_count = serializers.IntegerField(
        allow_null=True,
        help_text="Estimated number of positive examples (users who performed the target event).",
    )
    negative_count = serializers.IntegerField(
        allow_null=True,
        help_text="Estimated number of negative examples.",
    )
    base_rate = serializers.FloatField(
        allow_null=True,
        help_text="Fraction of the training population that performed the target event.",
    )
    inference_population_size = serializers.IntegerField(
        allow_null=True,
        help_text="Estimated number of users in the inference (daily scoring) population.",
    )
    warnings = ValidationWarningSerializer(
        many=True,
        help_text="List of validation warnings. Check 'severity' — 'error' blocks creation.",
    )
    error = serializers.CharField(
        allow_null=True,
        help_text="Internal error message if validation itself failed to run.",
    )


class StartTrainingRequestSerializer(serializers.Serializer):
    iteration_budget = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=500,
        help_text="Override the pipeline iteration budget for this training run.",
    )


# ── Agent-recorded training serializers ────────────────────────────────────


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Compact recipe for this iteration. Should contain feature_sql (a read-only HogQL SELECT "
            "keyed on person_id) and optional feature_transforms."
        ),
        "example": {
            "feature_sql": "SELECT person_id AS distinct_id, countIf(event='$pageview') AS pageviews FROM events GROUP BY person_id",
            "feature_transforms": [],
        },
    }
)
class IterationRecipeField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Model class and hyperparameters tried this iteration. model_class must be one of the "
            "allowlisted sklearn/xgboost classifiers."
        ),
        "example": {"model_class": "sklearn.linear_model.LogisticRegression", "model_params": {"C": 1.0}},
    }
)
class ModelSpecField(serializers.JSONField):
    pass


class OpenTrainingRunSerializer(serializers.Serializer):
    """Input for opening an agent-driven training run."""

    iteration_budget = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=500,
        help_text="Iteration budget for this run. Defaults to the pipeline's iteration_budget if omitted.",
    )


class RecordIterationSerializer(serializers.Serializer):
    """Input for recording one training iteration. Validated against the recipe allowlist."""

    iteration_number = serializers.IntegerField(
        min_value=0,
        help_text="Zero-based index of this iteration within the run. Re-sending the same number updates that iteration (idempotent).",
    )
    recipe_snapshot = IterationRecipeField(
        help_text="Compact recipe for this iteration: feature_sql (HogQL SELECT keyed on person_id) and transforms.",
    )
    model_spec = ModelSpecField(
        help_text="model_class (must be allowlisted) and model_params tried this iteration.",
    )
    status = serializers.ChoiceField(
        choices=["kept", "discarded", "crashed"],
        help_text="'kept' if this iteration improved on the best score, 'discarded' otherwise, 'crashed' on failure.",
    )
    train_score = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Training-set AUC for this iteration.",
    )
    holdout_score = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Held-out AUC for this iteration. Used to pick the champion at completion.",
    )
    agent_description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Agent's plain-English rationale for this iteration.",
    )
    agent_confidence = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=1,
        help_text="Agent's self-assessed confidence (0–1) that this iteration helps.",
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            validate_recipe(model_spec=data.get("model_spec") or {}, recipe_snapshot=data.get("recipe_snapshot") or {})
        except RecipeValidationError as e:
            raise serializers.ValidationError(str(e)) from e
        return data


class CompleteTrainingRunSerializer(serializers.Serializer):
    """Input for finalizing a training run. The backend selects/promotes the champion."""

    best_iteration_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Iteration to promote as champion candidate. If omitted, the kept iteration with the highest holdout_score is used.",
    )
    model_explanation = ModelExplanationField(
        required=False,
        default=dict,
        help_text="Global feature importance / directionality bundle for the champion model card.",
    )
    recommended_next = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "What a future run should try next, given what this run learned. Stored in the run summary so the "
            "next run reads it during orientation. Keep it short and concrete."
        ),
    )
    distillation = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "A 1–2 sentence distillation of what this run learned — the winning signal, the key transform, the "
            "dead-ends. Stored in the run summary as the cheapest thing the next run reads."
        ),
    )


# ── Feature materialization serializers ─────────────────────────────────────


class MaterializeFeaturesRequestSerializer(serializers.Serializer):
    """Input for materializing the labeled training feature matrix into the run's sandbox."""

    features_sql = serializers.CharField(
        help_text=(
            "Your HogQL feature query, using the {anchors}/{lookback_days} contract. Must be a read-only "
            "SELECT keyed on person_id (aliased to distinct_id), one row per user. The backend runs it "
            "server-side against the labeled training population — no 500-row cap — and writes the resulting "
            "train/holdout feature and label parquet files into your sandbox."
        ),
    )


class MaterializeFeaturesResponseSerializer(serializers.Serializer):
    """The local sandbox paths and shape of the materialized training matrix."""

    train_features_path = serializers.CharField(
        help_text="Sandbox path to the training feature matrix parquet (distinct_id + numeric feature columns)."
    )
    train_labels_path = serializers.CharField(
        help_text="Sandbox path to the training labels parquet (distinct_id + __label)."
    )
    holdout_features_path = serializers.CharField(
        help_text="Sandbox path to the holdout feature matrix parquet (same columns as train_features)."
    )
    holdout_labels_path = serializers.CharField(
        help_text="Sandbox path to the holdout labels parquet (distinct_id + __label)."
    )
    n_train = serializers.IntegerField(help_text="Number of rows in the training split.")
    n_holdout = serializers.IntegerField(help_text="Number of rows in the holdout split.")
    n_features = serializers.IntegerField(help_text="Number of numeric feature columns produced by features_sql.")
    feature_cols = serializers.ListField(
        child=serializers.CharField(),
        help_text="The numeric feature column names (excludes distinct_id, __label, __fold).",
    )


# ── Artifact bundle serializers ─────────────────────────────────────────────


class ArtifactUploadSerializer(serializers.Serializer):
    """Input for uploading one file of a training run's artifact bundle."""

    path = serializers.CharField(
        max_length=500,
        help_text=(
            "Relative path within the bundle, e.g. 'train.py', 'predict.py', 'features.sql', "
            "or 'eda/iter-3-gbm.ipynb'. Segments are limited to [A-Za-z0-9_.-]; "
            "absolute paths and '..' traversal are rejected."
        ),
    )
    content_base64 = serializers.CharField(
        help_text=(
            "File contents, base64-encoded. Decoded server-side and written to object storage. Max 10 MB decoded."
        ),
    )


class ArtifactPathSerializer(serializers.Serializer):
    """Input for fetching or deleting one bundle file by path."""

    path = serializers.CharField(
        max_length=500,
        help_text="Relative path of the file within the bundle, e.g. 'train.py'.",
    )


class StoredArtifactSerializer(serializers.Serializer):
    """Result of an upload: where the file landed and its content hash."""

    path = serializers.CharField(help_text="Relative path the file was stored at.")
    size_bytes = serializers.IntegerField(help_text="Decoded file size in bytes.")
    sha256 = serializers.CharField(help_text="SHA-256 hex digest of the decoded file content.")


class ArtifactContentSerializer(serializers.Serializer):
    """A single bundle file's content, base64-encoded."""

    path = serializers.CharField(help_text="Relative path of the file within the bundle.")
    size_bytes = serializers.IntegerField(help_text="File size in bytes.")
    sha256 = serializers.CharField(help_text="SHA-256 hex digest of the file content.")
    content_base64 = serializers.CharField(help_text="File contents, base64-encoded.")


class ArtifactListSerializer(serializers.Serializer):
    """The relative paths present in a training run's bundle."""

    paths = serializers.ListField(
        child=serializers.CharField(),
        help_text="Relative paths of every file stored under this training run's bundle prefix.",
    )
    count = serializers.IntegerField(help_text="Number of files in the bundle.")


class ArtifactDeleteResultSerializer(serializers.Serializer):
    """Whether a delete removed an existing file."""

    path = serializers.CharField(help_text="Relative path targeted for deletion.")
    deleted = serializers.BooleanField(help_text="True if a file existed and was removed; False if nothing was there.")


# ── Suggestion serializers ─────────────────────────────────────────────────


class AutoresearchSuggestionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    linked_iteration_ids = serializers.SerializerMethodField(
        help_text="UUIDs of iterations spawned from this suggestion."
    )

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_linked_iteration_ids(self, obj: AutoresearchSuggestion) -> list[str]:
        return [str(pk) for pk in obj.iterations.values_list("id", flat=True)]

    class Meta:
        model = AutoresearchSuggestion
        fields = [
            "id",
            "pipeline",
            "prompt",
            "priority",
            "status",
            "source",
            "agent_response",
            "created_by",
            "linked_iteration_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "source",
            "agent_response",
            "created_by",
            "linked_iteration_ids",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "id": {"help_text": "Unique UUID of this suggestion."},
            "pipeline": {"help_text": "Pipeline this suggestion targets."},
            "prompt": {"help_text": "Free-text hypothesis or direction for the agent to explore."},
            "priority": {
                "help_text": "'try_next' instructs the agent to act on this before other iterations; 'consider' is advisory."
            },
            "status": {
                "help_text": "Lifecycle status: 'queued' (awaiting pickup), 'picked_up' (agent is applying as a constraint), 'acted_on' (agent spawned iterations), 'dismissed' (agent rejected with rationale)."
            },
            "source": {"help_text": "'user' for human-submitted suggestions; 'agent' for agent-generated hypotheses."},
            "agent_response": {
                "help_text": "Agent's note on how the suggestion was interpreted and acted upon. Populated after pickup."
            },
        }


class CreateSuggestionSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=2000,
        help_text="Free-text hypothesis or direction for the agent to explore, e.g. 'try a tree-based model' or 'remove recency features, I suspect leakage'.",
    )
    priority = serializers.ChoiceField(
        choices=["try_next", "consider"],
        default="consider",
        help_text="'try_next' asks the agent to act on this before other autonomous iterations; 'consider' is advisory context.",
    )


# ── Template serializers ───────────────────────────────────────────────────────


class TemplateInfoSerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text="Template identifier, e.g. 'likely_active_soon'. Pass to autoresearch-resolve-template-create.",
    )
    display_name = serializers.CharField(help_text="Human-readable template name.")
    description = serializers.CharField(help_text="What this template predicts and who it is for.")
    default_horizon_days = serializers.IntegerField(
        help_text="Default prediction horizon in days. Can be overridden when resolving.",
    )
    requires_user_event = serializers.BooleanField(
        help_text=(
            "If true, you must supply a target_event when resolving — the template does not auto-select one. "
            "Required for 'feature_adoption' and 'repeat_key_behavior'."
        ),
    )
    requires_activity_resolution = serializers.BooleanField(
        help_text=(
            "If true, the target event is automatically resolved from your event schema "
            "($pageview, $screen, or the highest-volume non-noisy event). "
            "You can override the resolved event when resolving the template."
        ),
    )
    notes = serializers.CharField(help_text="Usage guidance and implementation notes.")


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Semantic population filter compiled to HogQL by the training/inference harness. "
            "Supported kinds: 'performed_event_within_days' (users who did event in last N days), "
            "'person_first_seen_within_days' (new users by first-seen date), "
            "'active_not_performed_target' (active users who have NOT done the target event), "
            "'ever_performed_event' (users who have done the target event at least once)."
        ),
        "example": {"kind": "performed_event_within_days", "event": "$pageview", "days": 30},
    }
)
class PopulationSpecField(serializers.JSONField):
    pass


class ResolveTemplateRequestSerializer(serializers.Serializer):
    template_key = serializers.ChoiceField(
        choices=[
            "likely_active_soon",
            "at_risk_of_inactivity",
            "return_after_first_use",
            "feature_adoption",
            "repeat_key_behavior",
        ],
        help_text=(
            "Template to resolve. Use autoresearch-templates-list to see all available templates "
            "with descriptions. Required."
        ),
    )
    target_event = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text=(
            "Event or action name to use as the prediction target. "
            "Required for 'feature_adoption' and 'repeat_key_behavior'. "
            "Optional override for activity-based templates ('likely_active_soon', "
            "'at_risk_of_inactivity', 'return_after_first_use') — omit to use the auto-resolved event."
        ),
    )
    horizon_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=365,
        help_text="Override the template's default prediction horizon in days.",
    )


class ResolvedTemplateSerializer(serializers.Serializer):
    template_key = serializers.CharField(help_text="The template key that was resolved.")
    display_name = serializers.CharField(help_text="Human-readable template name.")
    description = serializers.CharField(help_text="What this template predicts.")
    suggested_name = serializers.CharField(
        help_text="Suggested pipeline name. Pass as 'name' to autoresearch-create.",
    )
    target_event = serializers.CharField(
        help_text=(
            "Resolved target event. Pass as 'target_event' to autoresearch-create. "
            "For activity-based templates this is the auto-resolved activity event (or your override)."
        ),
    )
    resolved_activity_event = serializers.CharField(
        allow_null=True,
        help_text=(
            "Activity event found in your event schema, populated only for templates that "
            "auto-resolve the target ('likely_active_soon', 'at_risk_of_inactivity', "
            "'return_after_first_use'). Null for templates where you supply target_event directly."
        ),
    )
    activity_event_alternatives = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Other viable activity events found in your schema. "
            "If the resolved event is not the right signal, re-resolve with one of these as target_event."
        ),
    )
    horizon_days = serializers.IntegerField(help_text="Resolved prediction horizon in days.")
    training_population = PopulationSpecField(
        help_text=("Resolved training population filter. Pass as 'training_population' to autoresearch-create."),
    )
    inference_population = PopulationSpecField(
        help_text=(
            "Resolved inference (daily scoring) population filter. "
            "Pass as 'inference_population' to autoresearch-create."
        ),
    )
    output_person_property = serializers.CharField(
        help_text="Suggested person property name for prediction scores. Pass as 'output_person_property' to autoresearch-create.",
    )
    notes = serializers.CharField(help_text="Usage notes and guidance for interpreting this resolved config.")
