from typing import Any

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchTrainingRun,
)

# ── Typed schema wrappers for JSONField -----------------------------------


class TargetDefinitionField(serializers.JSONField):
    """Full target definition: event filters and positive-label logic."""

    class Meta:
        swagger_schema_fields = {
            "type": "object",
            "description": "Full target definition. May include event filters, action IDs, and positive-label conditions.",
            "example": {"event": "$pageview", "filters": []},
        }


class PopulationDefinitionField(serializers.JSONField):
    """HogQL cohort or property filter definition for a training/inference population."""

    class Meta:
        swagger_schema_fields = {
            "type": "object",
            "description": "Population definition as a HogQL cohort or filter object. "
            "Use {} for 'all identified users'.",
            "example": {"properties": [{"key": "email", "type": "person", "operator": "is_set"}]},
        }


class ModelRecipeField(serializers.JSONField):
    """Portable, versioned model recipe: feature SQL, transforms, model class, params."""

    class Meta:
        swagger_schema_fields = {
            "type": "object",
            "description": "Portable recipe artifact. Contains feature_sql (HogQL), feature_transforms, "
            "model_class, model_params, fit_signature, trained_on, holdout_score, and agent_description.",
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


class ModelExplanationField(serializers.JSONField):
    """Global model explanation: top feature importances, directionality, and leakage warnings."""

    class Meta:
        swagger_schema_fields = {
            "type": "object",
            "description": "Global feature importance bundle: top features by gain, directionality "
            "(positive/negative impact on predicted probability), stability across runs, "
            "and leakage warning annotations.",
        }


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
