import re
from dataclasses import replace
from typing import Any

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.shared import UserBasicSerializer

from products.autoresearch.backend.facade import api
from products.autoresearch.backend.facade.contracts import Pipeline, PipelineWrite

POPULATION_KINDS = api.POPULATION_KINDS

# (value, label) pairs, not bare values: drf-spectacular builds each enum component's name and
# its label list from them, and `ENUM_NAME_OVERRIDES` matches on the value set.
PIPELINE_STATUS_CHOICES = api.PIPELINE_STATUS_CHOICES

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
