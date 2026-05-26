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

    class Meta:
        model = AutoresearchPipeline
        fields = [
            "id",
            "name",
            "description",
            "target_event",
            "target_definition",
            "horizon_days",
            "prediction_mode",
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
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "last_scored_at",
            "iteration_budget_remaining",
            "status",
        ]
        extra_kwargs = {
            "id": {"help_text": "Unique UUID of this pipeline."},
            "name": {"help_text": "Display name for the pipeline."},
            "description": {"help_text": "Optional free-text description."},
            "target_event": {"help_text": "PostHog event name to predict, e.g. '$pageview' or 'signed_up'."},
            "horizon_days": {
                "help_text": "Prediction horizon in days. The model predicts whether the target event occurs within this window."
            },
            "prediction_mode": {
                "help_text": "'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence."
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
            "prediction_mode",
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
            "prediction_mode": {
                "help_text": "'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence."
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
            data["output_person_property"] = f"predicted_p_{safe_name}"
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


class AutoresearchTrainingRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutoresearchTrainingRun
        fields = [
            "id",
            "pipeline",
            "task_run_id",
            "status",
            "iteration_budget",
            "iteration_count",
            "best_holdout_score",
            "error",
            "started_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "iteration_count",
            "best_holdout_score",
            "error",
            "started_at",
            "completed_at",
            "created_at",
        ]
        extra_kwargs = {
            "id": {"help_text": "Unique UUID of this training run."},
            "pipeline": {"help_text": "Pipeline this training run belongs to."},
            "task_run_id": {"help_text": "Task sandbox run ID. Null for stub/synchronous training runs."},
            "status": {"help_text": "Run status: pending, running, completed, or failed."},
            "iteration_budget": {"help_text": "Maximum iterations allowed for this run."},
            "iteration_count": {"help_text": "Number of iterations completed."},
            "best_holdout_score": {"help_text": "Best holdout AUC achieved across all iterations in this run."},
            "error": {"help_text": "Error message if the run failed."},
            "started_at": {"help_text": "Timestamp when the training run started."},
            "completed_at": {"help_text": "Timestamp when the training run completed or failed."},
        }


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
    prediction_mode = serializers.ChoiceField(
        choices=["adoption", "continuation"],
        default="adoption",
        help_text="'adoption': predict first-time occurrence for users who haven't done it yet. "
        "'continuation': predict repeat occurrence for users who have already done it.",
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
