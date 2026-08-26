import re
from dataclasses import replace
from typing import Any

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.shared import UserBasicSerializer

from products.autoresearch.backend.facade import api
from products.autoresearch.backend.facade.contracts import (
    AutoresearchConflict,
    Iteration,
    IterationTrailEntry,
    Model,
    Pipeline,
    PipelineWrite,
    Run,
    Suggestion,
    TrainingRun,
)

POPULATION_KINDS = api.POPULATION_KINDS

# (value, label) pairs, not bare values: drf-spectacular builds each enum component's name and
# its label list from them, and `ENUM_NAME_OVERRIDES` matches on the value set.
PIPELINE_STATUS_CHOICES = api.PIPELINE_STATUS_CHOICES
MODEL_ROLE_CHOICES = api.MODEL_ROLE_CHOICES
RUN_STATUS_CHOICES = api.RUN_STATUS_CHOICES
RUN_TYPE_CHOICES = api.RUN_TYPE_CHOICES
TRAINING_RUN_STATUS_CHOICES = api.TRAINING_RUN_STATUS_CHOICES
ITERATION_STATUS_CHOICES = api.ITERATION_STATUS_CHOICES
SUGGESTION_PRIORITY_CHOICES = api.SUGGESTION_PRIORITY_CHOICES
SUGGESTION_STATUS_CHOICES = api.SUGGESTION_STATUS_CHOICES
SUGGESTION_SOURCE_CHOICES = api.SUGGESTION_SOURCE_CHOICES

TARGET_EVENT_MAX_LENGTH = 255
OUTPUT_PERSON_PROPERTY_MAX_LENGTH = 255

# The target event is interpolated into the sandboxed training agent's prompt brief, so reject
# characters that could break out of it (control chars incl. newlines, backticks, template braces)
# while keeping real event names ('$pageview', 'signed up', 'app.download-file') valid.
_FORBIDDEN_TARGET_EVENT_CHARS = re.compile(r"[\x00-\x1f\x7f`{}]")

_OUTPUT_PERSON_PROPERTY_RE = re.compile(r"^[A-Za-z0-9_$][A-Za-z0-9_$.\-]*$")


def _validate_target_event_value(value: str, *, error_key: str) -> None:
    if len(value) > TARGET_EVENT_MAX_LENGTH:
        raise serializers.ValidationError(
            {error_key: f"Target event names are limited to {TARGET_EVENT_MAX_LENGTH} characters."}
        )
    if _FORBIDDEN_TARGET_EVENT_CHARS.search(value):
        raise serializers.ValidationError(
            {error_key: "Target event names cannot contain control characters, backticks, or braces."}
        )


def resolve_target(
    *,
    team: Any,
    target_event: str,
    target_definition: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """
    Validate and normalize a prediction target, returning (target_event, target_definition).

    Two shapes:
      - event target → target_event must be non-empty; the definition is normalized to
        ``{"type": "event"}``. Any other event-shaped definition (e.g. one carrying filters)
        is rejected — the labeler only compiles the bare event and action shapes, so accepting
        filters here would silently ignore them.
      - action target → ``{"type": "action", "action_id": N}``. The action must belong to
        ``team`` (IDOR guard). target_event is backfilled from the action name when not
        supplied, so display and output-person-property derivation keep working unchanged.

    The resolved event is bounded and charset-checked in both branches — an action name can be
    longer (400 chars) and freer than target_event's field validation allows, and the value ends
    up in the training agent's prompt brief.

    Raises serializers.ValidationError on a missing/foreign action, an empty event target, an
    unsupported definition shape, or an unsafe/oversized resolved event.
    """
    definition = target_definition or {}
    if definition.get("type") == "action":
        action_id = definition.get("action_id")
        if action_id is None:
            raise serializers.ValidationError({"target_definition": "Action target requires 'action_id'."})
        try:
            action_name, action_id = api.resolve_action_target(team.pk, action_id)
        except api.PipelineNotFound as exc:
            raise serializers.ValidationError({"target_definition": str(exc)}) from exc
        resolved_event = target_event or action_name or f"action_{action_id}"
        _validate_target_event_value(resolved_event, error_key="target_event" if target_event else "target_definition")
        return resolved_event, {"type": "action", "action_id": int(action_id)}

    if not target_event:
        raise serializers.ValidationError(
            {"target_event": "Provide a target_event, or an action target via target_definition."}
        )
    if definition and (definition.get("type") != "event" or set(definition) != {"type"}):
        raise serializers.ValidationError(
            {
                "target_definition": (
                    'Unsupported target_definition. Pass {"type": "action", "action_id": N} to predict an action, '
                    "or omit target_definition to predict target_event. Event filters are not supported."
                )
            }
        )
    _validate_target_event_value(target_event, error_key="target_event")
    return target_event, {"type": "event"}


# ── Typed schema wrappers for JSONField -----------------------------------


@extend_schema_field(
    {
        "type": "object",
        "description": (
            'Target definition. Two supported shapes: {"type": "event"} (predict target_event; the default) '
            'or {"type": "action", "action_id": N} (predict a PostHog action). Event filters are not supported.'
        ),
        "example": {"type": "event"},
    }
)
class TargetDefinitionField(serializers.JSONField):
    pass


# Required keys per semantic population kind, mirrored by the compiler in
# dataset/labeling.py (_build_population_kind_conditions). Validated here so an
# uncompilable spec is rejected at creation instead of failing at query time.
_POPULATION_KIND_REQUIRED_DAYS: dict[str, str | None] = {
    "performed_event_within_days": "days",
    "person_first_seen_within_days": "days",
    "active_not_performed_target": "active_within_days",
    "ever_performed_event": None,
    "ever_performed_target": None,
}
_POPULATION_KIND_REQUIRES_EVENT = frozenset({"ever_performed_event"})
_POPULATION_DAYS_MAX = 730


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Population definition. Two shapes: a property filter object "
            '({"properties": [{"key": ..., "type": "person"|"event", "operator": ..., "value": ...}]}) '
            'or a semantic spec ({"kind": ..., ...}) as returned by autoresearch-resolve-template-create. '
            "Supported kinds: 'performed_event_within_days' (did event, or any event, in last 'days' days), "
            "'person_first_seen_within_days' (first seen within 'days' days), "
            "'active_not_performed_target' (any event in last 'active_within_days' days and has not done the "
            "pipeline's target), "
            "'ever_performed_event' (did 'event' at least once in the training lookback window), "
            "'ever_performed_target' (did the pipeline's target at least once in the training lookback window). "
            "Use {} for all identified users."
        ),
        "example": {"properties": [{"key": "email", "type": "person", "operator": "is_set"}]},
    }
)
class PopulationDefinitionField(serializers.JSONField):
    def to_internal_value(self, data: Any) -> Any:
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Population must be an object. Use {} for all identified users.")
        properties = value.get("properties")
        if properties is not None and (
            not isinstance(properties, list) or any(not isinstance(p, dict) for p in properties)
        ):
            raise serializers.ValidationError("Population 'properties' must be a list of filter objects.")
        kind = value.get("kind")
        if kind is None:
            return value
        if kind not in POPULATION_KINDS:
            raise serializers.ValidationError(
                f"Unknown population kind '{kind}'. Supported kinds: {', '.join(sorted(POPULATION_KINDS))}."
            )
        days_key = _POPULATION_KIND_REQUIRED_DAYS[kind]
        if days_key is not None:
            days = value.get(days_key)
            if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= _POPULATION_DAYS_MAX:
                raise serializers.ValidationError(
                    f"Population '{days_key}' must be a whole number between 1 and {_POPULATION_DAYS_MAX}."
                )
        if kind in _POPULATION_KIND_REQUIRES_EVENT:
            event = value.get("event")
            if not event or not isinstance(event, str):
                raise serializers.ValidationError(
                    f"Population kind '{kind}' needs an 'event' naming the event it applies to."
                )
        return value


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Portable recipe artifact. Contains feature_sql (HogQL), feature_transforms, "
            "model_class, model_params, fit_signature, trained_on, holdout_score, and agent_description."
        ),
        "example": {
            "feature_sql": "SELECT a.person_id AS distinct_id, countIf(e.event='$pageview') AS pageviews_30d FROM {anchors} a LEFT JOIN events e ON e.person_id = a.person_id AND e.timestamp < fromUnixTimestamp(a.cutoff_ts) GROUP BY a.person_id",
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


@extend_schema_serializer(component_name="AutoresearchPipeline")
# Read representation of a pipeline. Every field is declared explicitly so the generated
# AutoresearchPipeline component keeps the shape it had when this was a ModelSerializer.
class AutoresearchPipelineSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique UUID of this pipeline.")
    name = serializers.CharField(max_length=255, help_text="Display name for the pipeline.")
    description = serializers.CharField(required=False, allow_blank=True, help_text="Optional free-text description.")
    target_event = serializers.CharField(
        max_length=255, help_text="PostHog event name to predict, e.g. '$pageview' or 'signed_up'."
    )
    target_definition = TargetDefinitionField(
        help_text='Resolved target definition: {"type": "event"} or {"type": "action", "action_id": N}.'
    )
    horizon_days = serializers.IntegerField(
        min_value=-2147483648,
        max_value=2147483647,
        required=False,
        help_text="Prediction horizon in days. The model predicts whether the target event occurs within this window.",
    )
    training_lookback_days = serializers.IntegerField(
        min_value=-2147483648,
        max_value=2147483647,
        required=False,
        help_text="How far back to look for training examples. Larger windows give more data but may include stale behavior.",
    )
    training_population = PopulationDefinitionField(
        help_text="Population used for training. Defines which users can appear as training examples."
    )
    inference_population = PopulationDefinitionField(
        help_text="Population scored daily. Typically broader than the training population."
    )
    cadence_days = serializers.IntegerField(
        min_value=-2147483648,
        max_value=2147483647,
        required=False,
        help_text="Re-score the inference population every N days.",
    )
    iteration_budget = serializers.IntegerField(
        min_value=-2147483648,
        max_value=2147483647,
        required=False,
        help_text="Total training iterations allowed for the autoresearch loop.",
    )
    iteration_budget_remaining = serializers.IntegerField(
        read_only=True, help_text="Iterations remaining in the current budget."
    )
    success_auc = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Target AUC threshold. Training stops early if this score is reached.",
    )
    plateau_iterations = serializers.IntegerField(
        min_value=-2147483648,
        max_value=2147483647,
        required=False,
        help_text="Stop training if no AUC improvement is seen in this many consecutive iterations.",
    )
    output_person_property = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Person property name that stores the daily prediction score, e.g. 'predicted_p_pageview'.",
    )
    status = serializers.ChoiceField(
        choices=PIPELINE_STATUS_CHOICES,
        read_only=True,
        help_text="Pipeline lifecycle status: draft, bootstrapping, running, converged, paused, or archived.",
    )
    created_by = UserBasicSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    last_scored_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="Timestamp of the most recent completed inference run."
    )
    champion_holdout_auc = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text="Offline holdout AUC of the current champion model (predictive accuracy on held-out training data).",
    )
    champion_realized_auc = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text="Realized online AUC of the current champion model, computed from mature predictions against actual outcomes.",
    )

    class Meta:
        dataclass = Pipeline
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


@extend_schema_serializer(component_name="AutoresearchPipelineCreate")
# Create and update body for a pipeline. Validation that needs to read stored rows — the action
# target, whether a model already exists, whether the output property is taken — goes through
# the facade.
class AutoresearchPipelineCreateSerializer(DataclassSerializer):
    name = serializers.CharField(max_length=255, help_text="Display name for the pipeline.")
    description = serializers.CharField(required=False, allow_blank=True, help_text="Optional free-text description.")
    target_event = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text=(
            "PostHog event name to predict, e.g. '$pageview' or 'signed_up'. "
            "Omit when predicting an action target (pass target_definition instead)."
        ),
    )
    target_definition = TargetDefinitionField(
        required=False,
        default=dict,
        help_text=(
            'Omit (or pass {"type": "event"}) to predict target_event; pass '
            '{"type": "action", "action_id": N} to predict a PostHog action. No other shapes are accepted.'
        ),
    )
    horizon_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=365,
        help_text="Prediction horizon in days (1-365). The model predicts whether the target event occurs within this window.",
    )
    training_lookback_days = serializers.IntegerField(
        required=False,
        min_value=7,
        max_value=730,
        help_text="How far back to look for training examples (7-730 days). Larger windows give more data but may include stale behavior. Default: 180.",
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
    cadence_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=365,
        help_text="Re-score the inference population every N days (1-365). Default: 1.",
    )
    iteration_budget = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=500,
        help_text="Total training iterations allowed for the autoresearch loop (1-500). Default: 50.",
    )
    success_auc = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Target AUC threshold. Training stops early if reached. Default: 0.75.",
    )
    plateau_iterations = serializers.IntegerField(
        required=False,
        min_value=-2147483648,
        max_value=2147483647,
        help_text="Stop training if no improvement in this many consecutive iterations. Default: 10.",
    )
    output_person_property = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text=(
            "Person property name for the prediction score, e.g. 'predicted_p_pageview'. "
            "Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only; "
            "must be unique among this project's non-archived pipelines."
        ),
    )

    class Meta:
        dataclass = PipelineWrite
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

    # Fields a trained model was fit against. Once any model exists they are frozen: scoring keeps
    # loading the trained artifact, so changing them would silently answer a different question.
    MODEL_DEFINING_FIELDS = (
        "target_event",
        "target_definition",
        "horizon_days",
        "training_lookback_days",
        "training_population",
        "inference_population",
    )

    @property
    def _pipeline_id(self) -> Any:
        return self.context.get("pipeline_id")

    def validate_output_person_property(self, value: str) -> str:
        if value and not _OUTPUT_PERSON_PROPERTY_RE.fullmatch(value):
            raise serializers.ValidationError(
                "Use only letters, digits, and _ $ . - characters, e.g. 'predicted_p_signup_7d'."
            )
        return value

    @staticmethod
    def _supplied(data: Any, name: str) -> bool:
        """Whether the request body carried this field.

        ``DataclassSerializer`` leaves an unset field as the ``empty`` sentinel rather than the
        dataclass default, which is the only way to tell "absent" from "sent as the default".
        """
        return getattr(data, name, empty) is not empty

    @classmethod
    def _value(cls, data: Any, name: str, fallback: Any = None) -> Any:
        return getattr(data, name) if cls._supplied(data, name) else fallback

    def _validate_model_defining_fields_unchanged(self, team: Any, data: Any) -> None:
        pipeline_id = self._pipeline_id
        if not api.pipeline_has_models(team.pk, pipeline_id):
            return
        stored = api.get_pipeline_definition(team.pk, pipeline_id)
        changed = []
        for field_name in self.MODEL_DEFINING_FIELDS:
            if not self._supplied(data, field_name):
                continue
            current, new = getattr(stored, field_name), getattr(data, field_name)
            if field_name == "target_definition":
                # An empty stored definition and the normalized {"type": "event"} mean the same thing.
                current, new = current or {"type": "event"}, new or {"type": "event"}
            if new != current:
                changed.append(field_name)
        if changed:
            raise serializers.ValidationError(
                dict.fromkeys(
                    changed,
                    "This field cannot be changed after a model has been trained for this pipeline. "
                    "Create a new pipeline to predict a different target.",
                )
            )

    def _derive_output_person_property(self, data: Any) -> str:
        raw = self._value(data, "target_event") or "target"
        safe_name = re.sub(r"[^a-z0-9._-]+", "_", raw.lstrip("$").lower()) or "target"
        # Include the horizon so two pipelines predicting the same target over different
        # horizons don't $set the same person property and clobber each other's scores.
        horizon = self._value(data, "horizon_days") or 7
        derived = f"predicted_p_{safe_name}_{horizon}d"
        if len(derived) > OUTPUT_PERSON_PROPERTY_MAX_LENGTH:
            raise serializers.ValidationError(
                {
                    "output_person_property": (
                        "The auto-derived property name is too long for this target. "
                        "Pass output_person_property explicitly."
                    )
                }
            )
        return derived

    def validate(self, data: Any) -> Any:
        # DataclassSerializer hands us the constructed dataclass, not a dict, and it is frozen —
        # so derived values are collected here and applied with one `replace`.
        team = self.context["get_team"]()
        updates: dict[str, Any] = {}
        # On a partial update that doesn't touch the target, leave it untouched —
        # only resolve when creating or when a target field is actually supplied.
        is_update = self._pipeline_id is not None
        target_supplied = self._supplied(data, "target_event") or self._supplied(data, "target_definition")
        if not is_update or target_supplied:
            target_event, target_definition = resolve_target(
                team=team,
                target_event=self._value(data, "target_event", ""),
                target_definition=self._value(data, "target_definition"),
            )
            updates["target_event"] = target_event
            updates["target_definition"] = target_definition
        if is_update:
            self._validate_model_defining_fields_unchanged(team, replace(data, **updates) if updates else data)
        output_person_property = self._value(data, "output_person_property")
        if not is_update and not output_person_property:
            output_person_property = self._derive_output_person_property(replace(data, **updates) if updates else data)
            updates["output_person_property"] = output_person_property
        if output_person_property and api.output_person_property_taken(
            team.pk, output_person_property, exclude_pipeline_id=self._pipeline_id
        ):
            raise serializers.ValidationError(
                {
                    "output_person_property": (
                        f"Another pipeline in this project already writes to '{output_person_property}'. "
                        "Choose a different output_person_property."
                    )
                }
            )
        if not is_update and not self._value(data, "inference_population"):
            updates["inference_population"] = self._value(data, "training_population", {})
        return replace(data, **updates) if updates else data


@extend_schema_serializer(component_name="AutoresearchModel")
class AutoresearchModelSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique UUID of this model version.")
    pipeline = serializers.UUIDField(help_text="Pipeline this model belongs to.")
    role = serializers.ChoiceField(
        choices=MODEL_ROLE_CHOICES,
        required=False,
        help_text="Model role: 'champion' (active scoring model), 'challenger' (shadow model), or 'archived'.",
    )
    recipe_hash = serializers.CharField(
        read_only=True,
        help_text="SHA-256 of the serialized recipe. Used to deduplicate identical recipes across runs.",
    )
    model_recipe = ModelRecipeField(
        help_text="Portable recipe artifact. Feature SQL, transforms, model class, params, and metadata."
    )
    model_explanation = ModelExplanationField(
        help_text="Global feature importance and directionality. Used to explain top drivers on the model card."
    )
    holdout_score = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="AUC on the held-out test split at training time. Preliminary signal before online labels mature.",
    )
    realized_score = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Online AUC computed from actual realized outcomes. Authoritative once enough labels have matured.",
    )
    calibration_error = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Expected calibration error (ECE). Lower is better; well-calibrated models have ECE < 0.05.",
    )
    metrics = serializers.JSONField(
        required=False,
        help_text="Extended metrics bundle: Brier score, precision/recall at thresholds, lift@k, base rate, row counts.",
    )
    source_training_run = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Training run that produced this model. Read that run's artifact bundle to reuse the "
            "champion's train.py and features.sql as a starting point. Null for legacy models."
        ),
    )
    agent_description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="The agent's own plain-English description of what this recipe does and why it was chosen.",
    )
    trained_on_start = serializers.DateField(
        required=False, allow_null=True, help_text="Start of the training data window (inclusive)."
    )
    trained_on_end = serializers.DateField(
        required=False, allow_null=True, help_text="End of the training data window (exclusive)."
    )
    is_preliminary = serializers.BooleanField(
        required=False,
        help_text="True if this model has not yet been validated against realized online outcomes.",
    )
    promoted_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Timestamp when this model was promoted to champion."
    )
    archived_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Timestamp when this model was archived (superseded or retired).",
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        dataclass = Model
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
            "source_training_run",
            "agent_description",
            "trained_on_start",
            "trained_on_end",
            "is_preliminary",
            "promoted_at",
            "archived_at",
            "created_at",
            "updated_at",
        ]


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


@extend_schema_serializer(component_name="IterationTrail")
class IterationTrailSerializer(DataclassSerializer):
    """Compact, read-only view of one iteration for the cross-run history feed and the Training tab."""

    iteration_number = serializers.IntegerField(
        min_value=-2147483648, max_value=2147483647, help_text="Order of this attempt within its run (0-based)."
    )
    status = serializers.ChoiceField(
        choices=ITERATION_STATUS_CHOICES,
        help_text="Whether this recipe was kept (improved the best score), discarded, or crashed.",
    )
    holdout_score = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Holdout AUC this iteration achieved. Null if it was skipped/degenerate.",
    )
    train_score = serializers.FloatField(
        required=False, allow_null=True, help_text="Train-fold AUC for this iteration, if recorded."
    )
    agent_description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="The agent's one-line rationale for what it tried and why.",
    )
    model_spec = serializers.JSONField(help_text="Model class and hyperparameters tried in this iteration.")

    class Meta:
        dataclass = IterationTrailEntry
        fields = [
            "iteration_number",
            "status",
            "holdout_score",
            "train_score",
            "agent_description",
            "model_spec",
        ]


@extend_schema_serializer(component_name="AutoresearchTrainingRun")
class AutoresearchTrainingRunSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique UUID of this training run.")
    pipeline = serializers.UUIDField(help_text="Pipeline this training run belongs to.")
    task_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Parent Task ID in the tasks sandbox. Null for stub runs."
    )
    task_run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Task sandbox run ID. Null for stub/synchronous training runs.",
    )
    task_url = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Relative URL to the underlying sandbox Task detail page. Null for stub/synchronous training runs.",
    )
    status = serializers.ChoiceField(
        choices=TRAINING_RUN_STATUS_CHOICES,
        read_only=True,
        help_text="Run status: pending, running, completed, or failed.",
    )
    iteration_budget = serializers.IntegerField(
        min_value=-2147483648,
        max_value=2147483647,
        required=False,
        help_text="Maximum iterations allowed for this run.",
    )
    iteration_count = serializers.IntegerField(read_only=True, help_text="Number of iterations completed.")
    best_holdout_score = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text="Best holdout AUC achieved across all iterations in this run.",
    )
    summary = TrainingRunSummarySerializer(
        read_only=True,
        allow_null=True,
        help_text="Distilled cross-run learning summary written on completion. Null until the run completes.",
    )
    iterations = IterationTrailSerializer(
        many=True,
        read_only=True,
        help_text="Per-iteration breakdown — every recipe the agent tried this run, kept or discarded, "
        "with its model spec, holdout/train AUC, and one-line rationale. Ordered by iteration_number.",
    )
    error = serializers.CharField(read_only=True, allow_blank=True, help_text="Error message if the run failed.")
    started_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="Timestamp when the training run started."
    )
    completed_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="Timestamp when the training run completed or failed."
    )
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        dataclass = TrainingRun
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
            "iterations",
            "error",
            "started_at",
            "completed_at",
            "created_at",
        ]


@extend_schema_serializer(component_name="AutoresearchIteration")
class AutoresearchIterationSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    pipeline = serializers.UUIDField()
    training_run = serializers.UUIDField()
    iteration_number = serializers.IntegerField(
        min_value=-2147483648,
        max_value=2147483647,
    )
    recipe_hash = serializers.CharField(max_length=64)
    recipe_snapshot = serializers.JSONField(
        help_text="Compact recipe snapshot at time of iteration. Full artifact lives in the model row."
    )
    model_spec = serializers.JSONField(help_text="Model class and hyperparameters tried in this iteration.")
    train_score = serializers.FloatField(required=False, allow_null=True)
    holdout_score = serializers.FloatField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=ITERATION_STATUS_CHOICES)
    agent_description = serializers.CharField(required=False, allow_blank=True)
    agent_confidence = serializers.FloatField(
        required=False, allow_null=True, help_text="Agent's self-assessed confidence 0–1"
    )
    parent_suggestion = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of the steering suggestion this iteration was spawned from, if any.",
    )
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        dataclass = Iteration
        fields = [
            "id",
            "pipeline",
            "training_run",
            "iteration_number",
            "recipe_hash",
            "recipe_snapshot",
            "model_spec",
            "train_score",
            "holdout_score",
            "status",
            "agent_description",
            "agent_confidence",
            "parent_suggestion",
            "created_at",
        ]


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


@extend_schema_serializer(component_name="AutoresearchRun")
class AutoresearchRunSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique UUID of this run.")
    pipeline = serializers.UUIDField(help_text="Pipeline this run belongs to.")
    model = serializers.UUIDField(
        required=False, allow_null=True, help_text="Model used for scoring. Null for validation runs."
    )
    run_type = serializers.ChoiceField(
        choices=RUN_TYPE_CHOICES,
        help_text="Type of run: 'inference' (daily scoring) or 'validation' (outcome evaluation).",
    )
    status = serializers.ChoiceField(
        choices=RUN_STATUS_CHOICES,
        required=False,
        help_text="Run status: pending, running, completed, or failed.",
    )
    rows_scored = serializers.IntegerField(
        min_value=-2147483648,
        max_value=2147483647,
        required=False,
        allow_null=True,
        help_text="Number of users scored in this inference run.",
    )
    metrics = serializers.JSONField(
        help_text="Run metrics: rows scored, score distribution summary, validation AUC, etc."
    )
    error = serializers.CharField(required=False, allow_blank=True, help_text="Error message if the run failed.")
    started_at = serializers.DateTimeField(required=False, allow_null=True, help_text="Timestamp when the run started.")
    completed_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Timestamp when the run completed or failed."
    )
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        dataclass = Run
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
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Event name to predict, e.g. '$pageview'. Must exist in the team's event schema. "
            "Omit when predicting an action target (pass target_definition instead)."
        ),
    )
    target_definition = serializers.JSONField(
        required=False,
        default=dict,
        help_text=(
            'Optional target definition. Pass {"type": "action", "action_id": N} to predict a '
            "PostHog action (multi-step / property / autocapture matcher) instead of a single event."
        ),
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
    training_population = PopulationDefinitionField(
        default=dict,
        help_text="Population filter for training examples. Use {} for all identified users.",
    )
    inference_population = PopulationDefinitionField(
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
        min_value=0,
        max_value=1,
        help_text="Training-set AUC for this iteration (0-1).",
    )
    holdout_score = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=1,
        help_text="Held-out AUC for this iteration (0-1). Used to pick the champion at completion.",
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
    parent_suggestion = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "UUID of the steering suggestion this iteration was spawned from, if any. Set it whenever the "
            "iteration acts on a pending suggestion — it links the iteration back to the suggestion for "
            "attribution and advances the suggestion to 'acted_on'."
        ),
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            api.validate_iteration_recipe(
                model_spec=data.get("model_spec") or {}, recipe_snapshot=data.get("recipe_snapshot") or {}
            )
        except AutoresearchConflict as e:
            raise serializers.ValidationError(str(e)) from e
        return data


class RespondToSuggestionSerializer(serializers.Serializer):
    """Input for the agent to record how it interpreted a steering suggestion."""

    status = serializers.ChoiceField(
        choices=["picked_up", "acted_on", "dismissed"],
        help_text=(
            "How the agent handled the suggestion: 'picked_up' (applied as a search constraint), "
            "'acted_on' (spawned one or more iterations), or 'dismissed' (rejected — explain why in agent_response)."
        ),
    )
    agent_response = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        help_text="Plain-English note on how the suggestion was interpreted and acted upon (or why it was dismissed).",
    )


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
        max_length=2000,
        help_text=(
            "What a future run should try next, given what this run learned. Stored in the run summary so the "
            "next run reads it during orientation. Keep it short and concrete; max 2000 characters."
        ),
    )
    distillation = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        help_text=(
            "A 1–2 sentence distillation of what this run learned — the winning signal, the key transform, the "
            "dead-ends. Stored in the run summary as the cheapest thing the next run reads. Max 2000 characters."
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


@extend_schema_serializer(component_name="AutoresearchSuggestion")
class AutoresearchSuggestionSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique UUID of this suggestion.")
    pipeline = serializers.UUIDField(help_text="Pipeline this suggestion targets.")
    prompt = serializers.CharField(help_text="Free-text hypothesis or direction for the agent to explore.")
    priority = serializers.ChoiceField(
        choices=SUGGESTION_PRIORITY_CHOICES,
        required=False,
        help_text="'try_next' instructs the agent to act on this before other iterations; 'consider' is advisory.",
    )
    status = serializers.ChoiceField(
        choices=SUGGESTION_STATUS_CHOICES,
        read_only=True,
        help_text="Lifecycle status: 'queued' (awaiting pickup), 'picked_up' (agent is applying as a constraint), 'acted_on' (agent spawned iterations), 'dismissed' (agent rejected with rationale).",
    )
    # Named `source` to keep the field the API already exposes; it shadows DRF's own
    # Field.source attribute, which is a typing conflict only.
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=SUGGESTION_SOURCE_CHOICES,
        read_only=True,
        help_text="'user' for human-submitted suggestions; 'agent' for agent-generated hypotheses.",
    )
    agent_response = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="Agent's note on how the suggestion was interpreted and acted upon. Populated after pickup.",
    )
    created_by = UserBasicSerializer(read_only=True)
    linked_iteration_ids = serializers.ListField(
        child=serializers.UUIDField(),
        read_only=True,
        help_text="UUIDs of iterations spawned from this suggestion.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        dataclass = Suggestion
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
