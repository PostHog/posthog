import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, cast

from django.core.cache import cache
from django.db import models, transaction
from django.db.models import Q, QuerySet
from django.http import Http404

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.hogql import ast

from posthog.api.fields import RepeatedOrCommaSeparatedListField
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.event_usage import report_user_action
from posthog.hogql_queries.ai.ai_table_resolver import AIEventsUnavailableError
from posthog.models.team import Team
from posthog.permissions import AccessControlPermission, is_service_auth
from posthog.rate_limit import (
    AIObservabilityEvaluationJudgeTestTeamThrottle,
    AIObservabilityEvaluationJudgeTestThrottle,
)
from posthog.temporal.ai_observability.model_resolution import active_key_fallback
from posthog.temporal.ai_observability.run_evaluation import run_hog_eval
from posthog.temporal.ai_observability.run_session_evaluation import run_hog_eval_over_recent_sessions
from posthog.temporal.ai_observability.run_trace_evaluation import run_hog_eval_over_recent_traces

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.access_control.backend.facade.property_access import restriction_fingerprint
from products.access_control.backend.presentation.access_control import (
    AccessControlViewSetMixin,
    UserAccessControlSerializerMixin,
)

from ..evaluation_conditions import build_condition_filter
from ..facade import (
    api as facade,
    contracts,
)
from ..facade.contracts import Contract
from ..hog import compile_ai_observability_hog, hog_compile_error_message
from ..llm import DEFAULT_MODEL_BY_PROVIDER, supports_reasoning_level
from ..llm.decisions import is_decision_model
from ..llm.errors import ProviderConnectionError
from ..llm.providers.openai import OpenAIConfig
from ..llm.providers.openrouter import is_non_chat_model
from ..logic.evaluations.preview_outcomes import outcome_counts, preview_grader
from ..logic.evaluations.preview_queries import generation_io_preview, load_generation_events
from ..logic.evaluations.preview_units import session_quiet_period_seconds, trace_window_seconds
from ..models.evaluation_config import EvaluationConfig
from ..models.evaluation_configs import (
    EVALUATION_TEST_LOOKBACK_DAYS,
    MAX_CATEGORICAL_OPTIONS,
    SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MAX_MAX_AGE_SECONDS,
    SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MAX_WINDOW_SECONDS,
    SESSION_EVAL_MIN_MAX_AGE_SECONDS,
    SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MIN_WINDOW_SECONDS,
    SESSION_TEST_HOG_MAX_SAMPLES,
    TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    TRACE_EVAL_MAX_MAX_AGE_SECONDS,
    TRACE_EVAL_MAX_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_MAX_WINDOW_SECONDS,
    TRACE_EVAL_MIN_MAX_AGE_SECONDS,
    TRACE_EVAL_MIN_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_MIN_WINDOW_SECONDS,
    EvaluationType,
    OutputType,
    evaluation_supports_reports,
    evaluation_uses_model_configuration,
    get_evaluation_config_content_key,
    validate_evaluation_configs,
    validate_target_config,
)
from ..models.evaluation_directories import EvaluationDirectory
from ..models.evaluation_reports import EvaluationReport
from ..models.evaluations import Evaluation, EvaluationTarget
from ..models.model_configuration import LLMModelConfiguration
from ..models.provider_keys import LLMProvider, LLMProviderKey
from ..presentation.query_concurrency import query_concurrency_slots
from .condition_sets import ConditionSetSerializer
from .metrics import llma_track_latency

if TYPE_CHECKING:
    from posthog.models import User

    from ..logic.evaluations.period import PeriodBounds

logger = structlog.get_logger(__name__)


@extend_schema_field(
    {
        "oneOf": [
            {
                "type": "object",
                "title": "LLM judge config",
                "required": ["prompt"],
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.",
                        "minLength": 1,
                    },
                    "judge_method": {
                        "type": "string",
                        "enum": ["llm", "decision"],
                        "nullable": True,
                        "description": "Judge method. Omit to keep the saved method; null restores automatic routing.",
                    },
                    "include_media": {
                        "type": "boolean",
                        "description": "Set to false to judge text only.",
                    },
                    "reasoning_level": {
                        "type": "string",
                        "enum": ["minimal", "low", "medium", "high"],
                        "nullable": True,
                        "description": (
                            "How much the judge model reasons before it answers. Only Anthropic and OpenAI "
                            "reasoning models with the 'llm' judge method support it. Omit to keep the saved "
                            "level; null uses the model's default."
                        ),
                    },
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "title": "Hog config",
                "required": ["source"],
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Hog source code. Return a boolean, finite number, or category keys matching output_type. Categorical single selection accepts one key or a one-item list; multiple selection accepts a list, including []. Return null only for allowed N/A. Output settings determine which boolean counts as a failure.",
                        "minLength": 1,
                    }
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "title": "Sentiment config",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["user_messages"],
                        "description": (
                            "Classify sentiment from user messages in the generation input. The classifier is "
                            "trained on English, so labels are unreliable for other languages; use an 'llm_judge' "
                            "evaluation for multilingual agents."
                        ),
                        "default": "user_messages",
                    }
                },
                "additionalProperties": False,
            },
        ]
    }
)
class _EvaluationConfigField(serializers.JSONField):
    pass


# Keep defaults in BooleanOutputConfig: nested schema defaults become explicit MCP PATCH values
# and overwrite stored settings even when the caller omits them.
@extend_schema_field(
    {
        "type": "object",
        "properties": {
            "allows_na": {
                "type": "boolean",
                "description": "Whether the evaluation can return N/A for non-applicable generations.",
            },
            "true_is_failure": {
                "type": "boolean",
                "description": "Boolean output only. Omit for numeric, categorical, and sentiment "
                "output. Whether a true result means the evaluation found "
                "a problem. False (the default) suits pass/fail "
                "evaluations, where a true result satisfied the criteria. "
                "Set it to true for detector-style evaluations, so a true "
                "result is counted and labeled as a fail.",
            },
            "decision_threshold": {
                "type": "number",
                "nullable": True,
                "minimum": 0,
                "maximum": 1,
                "description": "Boolean decision-model judges only. Minimum probability of true required for a true result, inclusive. Omit or set null to use 0.5. Applies to new runs; historical results are unchanged.",
            },
            "min": {
                "type": "number",
                "nullable": True,
                "description": "Inclusive minimum numeric score. Omit for no lower bound. Required for numeric decision models.",
            },
            "max": {
                "type": "number",
                "nullable": True,
                "description": "Inclusive maximum numeric score. Omit for no upper bound. Required for numeric decision models and must exceed min.",
            },
            "step": {
                "type": "number",
                "nullable": True,
                "exclusiveMinimum": True,
                "minimum": 0,
                "description": "Optional positive input increment. Does not round evaluation results.",
            },
            "options": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_CATEGORICAL_OPTIONS,
                "description": "Categorical output options. Keys identify stored results; labels are displayed to users.",
                "items": {
                    "type": "object",
                    "required": ["key", "label"],
                    "properties": {
                        "key": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                            "pattern": "^[a-z0-9]+(?:[_-][a-z0-9]+)*$",
                            "description": "Stable category key.",
                        },
                        "label": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 256,
                            "description": "Category display label.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "selection_mode": {
                "type": "string",
                "enum": ["single", "multiple"],
                "description": "Select one category or multiple categories. Multiple selection allows an empty result. Defaults to single.",
            },
            "passing_rule": {
                "nullable": True,
                "description": "Optional numeric or categorical passing rule. Null removes the rule; historical results use the current rule.",
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["operator", "threshold"],
                        "properties": {
                            "operator": {
                                "type": "string",
                                "enum": ["gte", "lte"],
                                "description": "Pass at or above (gte), or at or below (lte), the threshold.",
                            },
                            "threshold": {
                                "type": "number",
                                "description": "Finite passing threshold within any configured score bounds.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "required": ["categories"],
                        "properties": {
                            "categories": {
                                "type": "array",
                                "uniqueItems": True,
                                "items": {"type": "string"},
                                "description": "Passing category keys. With keys selected, results must be non-empty and contain only these keys. If no passing keys are selected, only an empty result passes.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ],
            },
        },
        "additionalProperties": False,
    }
)
class _OutputConfigField(serializers.DictField):
    child = serializers.JSONField(allow_null=True)


# One object rather than a `oneOf` per strategy: a generated zod union strips the keys a branch does not
# declare, so a payload that matches the wrong branch loses its settings, and the empty config of a
# generation target matches no branch. `validate_target_config` checks the per-strategy combination.
@extend_schema_field(
    {
        "type": "object",
        "title": "Settle config",
        "properties": {
            "strategy": {
                "type": "string",
                "enum": ["fixed_window", "inactivity"],
                "description": (
                    "'fixed_window' waits a fixed window after the first matching generation, then evaluates. "
                    "'inactivity' evaluates once the unit has had no new activity for the quiet period. "
                    "Omit it to use the target's default: 'fixed_window' for 'trace', 'inactivity' for 'session'."
                ),
            },
            "window_seconds": {
                "type": "integer",
                "description": (
                    "fixed_window only. Seconds to wait after the first matching generation before evaluating "
                    "the whole unit. Captured when the run is scheduled — editing it does not change runs "
                    "already in flight. The accepted range depends on `target`: "
                    f"{TRACE_EVAL_MIN_WINDOW_SECONDS}–{TRACE_EVAL_MAX_WINDOW_SECONDS} for 'trace', "
                    f"{SESSION_EVAL_MIN_WINDOW_SECONDS}–{SESSION_EVAL_MAX_WINDOW_SECONDS} for 'session'. "
                    "The default also depends on `target`; see the field-level help_text."
                ),
                "minimum": min(TRACE_EVAL_MIN_WINDOW_SECONDS, SESSION_EVAL_MIN_WINDOW_SECONDS),
                "maximum": max(TRACE_EVAL_MAX_WINDOW_SECONDS, SESSION_EVAL_MAX_WINDOW_SECONDS),
            },
            "quiet_period_seconds": {
                "type": "integer",
                "description": (
                    "inactivity only. Seconds without new activity before the unit counts as settled. The "
                    f"accepted range depends on `target`: {TRACE_EVAL_MIN_QUIET_PERIOD_SECONDS}–"
                    f"{TRACE_EVAL_MAX_QUIET_PERIOD_SECONDS} for 'trace', "
                    f"{SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS}–{SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS} "
                    "for 'session'. The default also depends on `target`; see the field-level help_text."
                ),
                "minimum": min(TRACE_EVAL_MIN_QUIET_PERIOD_SECONDS, SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS),
                "maximum": max(TRACE_EVAL_MAX_QUIET_PERIOD_SECONDS, SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS),
            },
            "max_age_seconds": {
                "type": "integer",
                "description": (
                    "inactivity only. Hard cap in seconds on the total wait from the first matching generation, "
                    "even if the unit stays active. Must be at least quiet_period_seconds. The accepted range "
                    f"depends on `target`: {TRACE_EVAL_MIN_MAX_AGE_SECONDS}–{TRACE_EVAL_MAX_MAX_AGE_SECONDS} "
                    f"for 'trace', {SESSION_EVAL_MIN_MAX_AGE_SECONDS}–{SESSION_EVAL_MAX_MAX_AGE_SECONDS} for "
                    "'session'. The default also depends on `target`; see the field-level help_text."
                ),
                "minimum": min(TRACE_EVAL_MIN_MAX_AGE_SECONDS, SESSION_EVAL_MIN_MAX_AGE_SECONDS),
                "maximum": max(TRACE_EVAL_MAX_MAX_AGE_SECONDS, SESSION_EVAL_MAX_MAX_AGE_SECONDS),
            },
        },
        "additionalProperties": False,
    }
)
class _TargetConfigField(serializers.JSONField):
    pass


class ModelConfigurationSerializer(serializers.Serializer):
    """Nested serializer for model configuration."""

    provider = serializers.ChoiceField(choices=LLMProvider.choices)
    model = serializers.CharField(max_length=100)
    provider_key_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional team provider key to run this evaluation with; it must use the same provider. "
            "May be null when no key is pinned or after the selected key is removed."
        ),
    )
    provider_key_name = serializers.SerializerMethodField(read_only=True)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        errors = {field: "This field is required." for field in ("provider", "model") if field not in data}
        if errors:
            raise serializers.ValidationError(errors, code="required")
        if data["provider"] == LLMProvider.SYSTEM_ONE:
            if not data.get("provider_key_id"):
                raise serializers.ValidationError(
                    {"provider_key_id": "Select a System One connection for this evaluation."}
                )
        return data

    def get_provider_key_name(self, obj: LLMModelConfiguration) -> str | None:
        if obj.provider_key:
            return obj.provider_key.name
        return None

    def to_representation(self, instance: LLMModelConfiguration) -> dict[str, Any]:
        return {
            "provider": instance.provider,
            "model": instance.model,
            "provider_key_id": str(instance.provider_key_id) if instance.provider_key_id else None,
            "provider_key_name": instance.provider_key.name if instance.provider_key else None,
        }


class EvaluationConditionSerializer(ConditionSetSerializer):
    """A trigger condition set controlling which generations an evaluation runs on."""

    id = serializers.CharField(max_length=100, help_text="Stable identifier for this condition set.")
    rollout_percentage = serializers.FloatField(
        default=100,
        min_value=0,
        max_value=100,
        help_text="Percentage (0-100) of matching events to sample for this evaluation. Defaults to 100.",
    )
    properties = serializers.ListField(
        child=serializers.DictField(),
        default=list,
        help_text="Property filters (event or person) that scope which generations match this condition set.",
    )


class EvaluationSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    """An evaluation that scores LLM generations, traces, or sessions."""

    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the evaluation.",
    )
    directory_id = TeamScopedPrimaryKeyRelatedField(
        source="directory",
        queryset=EvaluationDirectory.objects.unscoped(),
        required=False,
        allow_null=True,
        help_text="Directory containing the evaluation. Pass null to move the evaluation to the top level.",
    )
    model_configuration = ModelConfigurationSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "Provider and model for an llm_judge evaluation. Required when creating or switching to llm_judge. "
            "To add or replace a model, provide both provider and model. On an existing configured llm_judge, "
            "omit this field to keep the current model; null is rejected. When switching an llm_judge to hog or "
            "sentiment, set this field to null. Legacy llm_judge evaluations without a model remain editable "
            "without adding one. The nested provider_key_id may be null."
        ),
    )
    status_reason_detail = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Additional detail for the current system-disabled status. This is only populated when the detail is "
            "safe to show in the evaluation UI."
        ),
    )
    evaluation_config = _EvaluationConfigField(
        required=False,
        help_text=(
            "Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; "
            "for 'sentiment': {source: 'user_messages'}."
        ),
    )
    output_config = _OutputConfigField(
        required=False,
        help_text=(
            "Output config. For 'boolean' output_type: {allows_na} to permit N/A results, and "
            "{true_is_failure} to declare that a true result means the evaluation found a problem. "
            "For boolean decision-model judges, decision_threshold is a probability from 0 to 1 (default 0.5). "
            "For 'numeric': only min/max/step, allows_na, and passing_rule {operator: 'gte'|'lte', threshold}. "
            "For 'categorical': options [{key, label}], selection_mode (single or multiple), allows_na, and optional passing_rule {categories: [key]}. Do not send true_is_failure for numeric or categorical output. For 'sentiment': {}."
        ),
    )
    target_config = _TargetConfigField(
        required=False,
        help_text=(
            "Target-specific config. Send {} or omit it for 'generation'. For 'trace' and 'session' targets: a "
            "settle config, either 'fixed_window' {window_seconds} or 'inactivity' {quiet_period_seconds, "
            "max_age_seconds}. Omit `strategy` to use the target's default. The server fills in any other "
            "field you omit, using per-target defaults, and the accepted bounds also depend on `target`."
        ),
    )
    conditions = EvaluationConditionSerializer(
        many=True,
        required=False,
        help_text=(
            "Trigger conditions that filter which events are evaluated. OR between condition sets, "
            "AND within each. Each set is {id, rollout_percentage, properties[]} — `rollout_percentage` "
            "(0-100, defaults to 100) is the sampling field the dispatcher reads."
        ),
    )

    class Meta:
        model = Evaluation
        fields = [
            "id",
            "name",
            "description",
            "directory_id",
            "enabled",
            "status",
            "status_reason",
            "status_reason_detail",
            "evaluation_type",
            "evaluation_config",
            "output_type",
            "output_config",
            "conditions",
            "target",
            "target_config",
            "model_configuration",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
            "user_access_level",
        ]
        # status / status_reason are server-managed (coerced from enabled on user writes, set directly by
        # system transitions). Clients toggle `enabled`; the model's save() keeps the status fields consistent.
        read_only_fields = [
            "id",
            "status",
            "status_reason",
            "status_reason_detail",
            "created_at",
            "updated_at",
            "created_by",
        ]
        extra_kwargs = {
            "name": {"help_text": "Name of the evaluation."},
            "description": {"help_text": "Optional description of what this evaluation checks."},
            "enabled": {"help_text": "Whether the evaluation runs automatically on new $ai_generation events."},
            "evaluation_type": {
                "help_text": (
                    "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code; "
                    "'sentiment' classifies user-message sentiment (trained on English, so use 'llm_judge' for "
                    "multilingual agents)."
                )
            },
            "output_type": {
                "help_text": (
                    "Output format: 'boolean', 'numeric' for a finite score, 'categorical' for category keys, or 'sentiment' for sentiment analysis."
                )
            },
            "target": {
                "help_text": (
                    "What the evaluation runs on. 'generation' evaluates each matching $ai_generation event "
                    "individually. 'trace' evaluates the whole trace once and 'session' the whole "
                    "$ai_session_id session once: the first matching generation schedules a run that waits "
                    "for the unit to settle, then evaluates all of its events together. Condition filters "
                    "still match individual generations — a unit is evaluated when any of its generations "
                    "matches, and sampling applies per unit. A 'session' evaluation only fires for "
                    "generations that carry $ai_session_id. When and how the run fires is controlled by "
                    "target_config's settle strategy."
                )
            },
            "deleted": {"help_text": "Set to true to soft-delete the evaluation."},
        }

    def _is_paused_without_model(self, data: dict[str, object]) -> bool:
        """An LLM judge that is created paused without a model, or stays that way through an edit. A team with
        no provider key has no model to pick, so the judge may wait for one. Turning it on runs
        `_validate_can_run`, which needs a key and a model that can run it.

        A new evaluation counts only when the payload sets `enabled` to false, so a request that forgot the
        model still gets the error. An edit counts only when it leaves the type and the judge method as they
        are, so choosing a method for an older evaluation still asks for a model."""
        if data.get("model_configuration") or data.get("enabled", False) is not False:
            return False
        if self.instance is None:
            return "enabled" in data
        config = data.get("evaluation_config", self.instance.evaluation_config)
        method = config.get("judge_method") if isinstance(config, dict) else None
        return (
            self.instance.evaluation_type == EvaluationType.LLM_JUDGE.value
            and data.get("evaluation_type", self.instance.evaluation_type) == EvaluationType.LLM_JUDGE.value
            and not self.instance.enabled
            and self.instance.model_configuration_id is None
            and method == (self.instance.evaluation_config or {}).get("judge_method")
        )

    def _uses_decision_model(self, data: dict[str, object]) -> bool:
        evaluation_type = data.get("evaluation_type") or getattr(self.instance, "evaluation_type", None)
        if evaluation_type != EvaluationType.LLM_JUDGE.value:
            return False

        stored_config = getattr(self.instance, "evaluation_config", {})
        evaluation_config = data.get("evaluation_config", stored_config)
        judge_method = evaluation_config.get("judge_method") if isinstance(evaluation_config, dict) else None
        method_changed = judge_method != stored_config.get("judge_method")
        should_validate_model = (
            self.instance is None
            or bool({"model_configuration", "evaluation_type", "output_type", "output_config"} & data.keys())
            or data.get("enabled", False)
            or method_changed
        )
        if not should_validate_model:
            return False

        model_configuration = self._effective_model_configuration(data) or {}
        if judge_method is not None and not model_configuration:
            if self._is_paused_without_model(data):
                return False
            raise serializers.ValidationError(
                {"model_configuration": "Select a provider and model for this LLM judge evaluation."}
            )
        model_provider = model_configuration.get("provider")
        if judge_method == "llm":
            if model_provider == "system_one":
                raise serializers.ValidationError({"model_configuration": "Select a model that supports LLM judging."})
            return False
        try:
            supports_decisions = is_decision_model(
                model_provider,
                model_configuration.get("model"),
                decision_only=judge_method is None,
                openai_enabled=judge_method == "decision"
                and model_provider == LLMProvider.OPENAI
                and model_configuration.get("model") in OpenAIConfig.DECISION_MODELS,
            )
        except ProviderConnectionError as e:
            raise serializers.ValidationError({"model_configuration": str(e)}) from e
        if judge_method == "decision" and not supports_decisions:
            raise serializers.ValidationError(
                {"model_configuration": "Select an available decision model for this judge method."}
            )
        return supports_decisions

    def validate(self, data):
        evaluation_type = data.get("evaluation_type") or getattr(self.instance, "evaluation_type", None)
        output_type = data.get("output_type") or getattr(self.instance, "output_type", None)
        requests_reasoning_level = isinstance(data.get("evaluation_config"), dict) and (
            "reasoning_level" in data["evaluation_config"]
        )
        if "evaluation_config" in data:
            config = data["evaluation_config"]
            if not isinstance(config, dict):
                raise serializers.ValidationError({"evaluation_config": "Must be an object."})
            if self.partial and self.instance is not None and evaluation_type == EvaluationType.LLM_JUDGE.value:
                # A prompt-only PATCH must not reset the saved judge settings or image opt-out.
                saved = {
                    key: self.instance.evaluation_config[key]
                    for key in ("judge_method", "reasoning_level", "include_media")
                    if key not in config and key in self.instance.evaluation_config
                }
                data["evaluation_config"] = {**saved, **config}
        if (
            self.instance
            and output_type != self.instance.output_type
            and ({output_type, self.instance.output_type} & {"numeric", "categorical"})
        ):
            raise serializers.ValidationError({"output_type": "Create a new evaluation to change its output type."})
        model_configuration = data.get(
            "model_configuration",
            getattr(self.instance, "model_configuration", None) if self.instance else None,
        )
        uses_decision_model = self._uses_decision_model(data)
        if uses_decision_model and output_type not in ("boolean", "categorical", "numeric"):
            raise serializers.ValidationError(
                {"model_configuration": "Select a model that supports this evaluation output type."}
            )

        if not evaluation_uses_model_configuration(evaluation_type) and model_configuration is not None:
            raise serializers.ValidationError(
                {"model_configuration": "This evaluation type does not use model configuration."}
            )

        if evaluation_uses_model_configuration(evaluation_type) and model_configuration is None:
            existing_uses_model_configuration = bool(
                self.instance and evaluation_uses_model_configuration(self.instance.evaluation_type)
            )
            newly_requires_model_configuration = self.instance is None or not existing_uses_model_configuration
            clears_existing_model_configuration = bool(
                self.instance and self.instance.model_configuration_id and "model_configuration" in data
            )
            if (
                newly_requires_model_configuration and not self._is_paused_without_model(data)
            ) or clears_existing_model_configuration:
                raise serializers.ValidationError(
                    {"model_configuration": "Select a provider and model for this LLM judge evaluation."}
                )

        method_changed = "evaluation_config" in data and data["evaluation_config"].get("judge_method") != getattr(
            self.instance, "evaluation_config", {}
        ).get("judge_method")
        if data.get("model_configuration") or data.get("enabled") or method_changed:
            self._validate_chat_model(data, uses_decision_model=uses_decision_model)
        self._validate_reasoning_level(
            data, uses_decision_model=uses_decision_model, requested=requests_reasoning_level
        )

        should_validate_configs = (
            self.instance is None
            or "evaluation_type" in data
            or "output_type" in data
            or "evaluation_config" in data
            or "output_config" in data
        )
        if should_validate_configs and evaluation_type and output_type:
            evaluation_config = data.get(
                "evaluation_config",
                getattr(self.instance, "evaluation_config", {}) if self.instance else {},
            )
            output_config = data.get(
                "output_config",
                getattr(self.instance, "output_config", {}) if self.instance else {},
            )
            if self.partial and self.instance is not None and "output_config" in data:
                output_config = {**self.instance.output_config, **output_config}
            try:
                data["evaluation_config"], data["output_config"] = validate_evaluation_configs(
                    evaluation_type, output_type, evaluation_config, output_config
                )
            except ValueError as e:
                raise serializers.ValidationError({"config": str(e)})

        if uses_decision_model and output_type == "numeric":
            config = data.get("output_config", getattr(self.instance, "output_config", {}))
            if config.get("min") is None or config.get("max") is None or config["min"] >= config["max"]:
                raise serializers.ValidationError(
                    {
                        "output_config": "Numeric evaluations with decision models require a minimum score below the maximum score."
                    }
                )

        if uses_decision_model and output_type == "categorical":
            model_configuration = self._effective_model_configuration(data) or {}
            config = data.get("output_config", getattr(self.instance, "output_config", {}))
            if (
                model_configuration.get("provider") == LLMProvider.OPENAI
                and config.get("selection_mode", "single") == "single"
                and len(config.get("options", [])) < 2
            ):
                raise serializers.ValidationError(
                    {
                        "output_config": "OpenAI decision models require at least two options for single-selection categories."
                    }
                )

        # Sentiment is addressed per-message within one generation event ($ai_target_event_id +
        # message index). An aggregate target emits a single evaluation event for the whole unit,
        # where the message index is ambiguous and that per-generation linkage is absent.
        # Aggregate-level sentiment is already produced by aggregating generation-target sentiment
        # evals at read time.
        effective_target = data.get("target") or getattr(self.instance, "target", None) or EvaluationTarget.GENERATION
        if evaluation_type == EvaluationType.SENTIMENT.value and effective_target != EvaluationTarget.GENERATION.value:
            raise serializers.ValidationError(
                {"target": "Sentiment evaluations can only target each generation. Choose the 'generation' target."}
            )

        # Validate target_config against the effective target (request value, else the stored one).
        # Surfaces a clean field error for an out-of-range window; the model's save() re-runs this
        # so untouched requests still get normalized.
        if "target" in data or "target_config" in data:
            stored_target = getattr(self.instance, "target", None)
            target = data.get("target") or stored_target or "generation"
            config = data.get("target_config")
            if config is None:
                # Carrying the stored bag across a target change would keep the old target's
                # strategy — a trace's fixed_window surviving onto a session means grading 30
                # minutes into a conversation instead of when it goes quiet, which is exactly what
                # DEFAULT_SETTLE_STRATEGY_BY_TARGET exists to prevent. Reseed instead, matching
                # what the form does client-side.
                config = {} if target != stored_target else getattr(self.instance, "target_config", {})
            try:
                data["target_config"] = validate_target_config(target, config or {})
            except ValueError as e:
                raise serializers.ValidationError({"target_config": str(e)})

        if data.get("enabled"):
            if self.instance is None:
                self._validate_can_run(data)
            elif not self.instance.enabled:
                self._validate_re_enable(data)

        return data

    def _validate_chat_model(self, data: dict, *, uses_decision_model: bool) -> None:
        """OpenRouter judges use either chat completions or typed decisions."""
        model_config = self._effective_model_configuration(data)
        if not model_config or model_config.get("provider") != LLMProvider.OPENROUTER:
            return
        model = model_config.get("model")
        if uses_decision_model:
            return
        if model and is_non_chat_model(model):
            raise serializers.ValidationError(
                {
                    "model_configuration": f"'{model}' is not supported as an evaluation judge. "
                    "Choose a chat model or a supported decision model."
                }
            )

    def _validate_reasoning_level(self, data: dict, *, uses_decision_model: bool, requested: bool) -> None:
        evaluation_type = data.get("evaluation_type") or getattr(self.instance, "evaluation_type", None)
        if evaluation_type != EvaluationType.LLM_JUDGE.value:
            return
        evaluation_config = data.get("evaluation_config", getattr(self.instance, "evaluation_config", None))
        if not isinstance(evaluation_config, dict) or not evaluation_config.get("reasoning_level"):
            return
        model_config = self._effective_model_configuration(data) or {}
        if uses_decision_model or not supports_reasoning_level(model_config.get("provider"), model_config.get("model")):
            if self.instance is not None and not requested:
                # A saved level must not block a model change. The create page drops it the same way.
                data["evaluation_config"] = {k: v for k, v in evaluation_config.items() if k != "reasoning_level"}
                return
            raise serializers.ValidationError(
                {
                    "evaluation_config": "This judge model doesn't support a reasoning level. Choose an Anthropic or OpenAI reasoning model, or use the model default."
                }
            )

    def _validate_can_run(self, data: dict) -> None:
        """An eval being turned on — created enabled or re-enabled — must be able to resolve a
        model at runtime; otherwise the caller gets a 200/201 and the first Temporal run silently
        disables it again."""
        evaluation_type = data.get("evaluation_type") or getattr(self.instance, "evaluation_type", None)
        if not evaluation_uses_model_configuration(evaluation_type):
            return

        provider_key = self._effective_provider_key(data)
        if provider_key is not None:
            if provider_key.state != LLMProviderKey.State.OK:
                raise serializers.ValidationError(
                    {"enabled": "Attach a working provider API key to enable this evaluation."}
                )
            return

        self._validate_keyless_resolution(data)

    def _validate_re_enable(self, data: dict) -> None:
        evaluation_type = data.get("evaluation_type") or getattr(self.instance, "evaluation_type", None)
        if not evaluation_uses_model_configuration(evaluation_type):
            return

        # _validate_can_run mirrors runtime resolution, so it already rejects a re-enable whose key is
        # missing/unhealthy or whose keyless config can't resolve — no separate provider-key gate needed.
        self._validate_can_run(data)

        status_reason = getattr(self.instance, "status_reason", None)

        if status_reason == "model_not_found" and not self._has_model_configuration_after_update(data):
            raise serializers.ValidationError(
                {"enabled": "Choose an available model before re-enabling this evaluation."}
            )

        # No default model: the team's active key is for a provider we have no default model for, and
        # the eval left its model unset. Require an explicit model so it can't immediately re-disable.
        if status_reason == "no_default_model":
            if not self._has_model_configuration_after_update(data):
                raise serializers.ValidationError(
                    {
                        "enabled": "This evaluation's provider has no default model. Set a model on the evaluation before re-enabling."
                    }
                )

    def _validate_keyless_resolution(self, data: dict) -> None:
        """Mirror the runtime model resolution for evals with no usable provider key (see
        `posthog/temporal/ai_observability/model_resolution.py`). A pinned key, or an explicit
        config's active-key fallback, is already handled by `_validate_can_run`; this covers what
        is left: a null config resolves via the team's active key, and anything else must add a
        provider key of its own."""
        team = self.context["get_team"]()
        config = EvaluationConfig.objects.filter(team=team).first()

        explicit_config = self._effective_model_configuration(data)
        if explicit_config is not None:
            raise serializers.ValidationError(
                {"enabled": self._missing_key_message(team, explicit_config.get("provider"))}
            )

        active_key = config.active_provider_key if config else None
        if active_key is None:
            raise serializers.ValidationError({"enabled": self._missing_key_message(team, None)})

        if active_key.state != LLMProviderKey.State.OK:
            raise serializers.ValidationError(
                {"enabled": "Attach a working provider API key to enable this evaluation."}
            )
        if DEFAULT_MODEL_BY_PROVIDER.get(active_key.provider) is None:
            raise serializers.ValidationError(
                {
                    "enabled": "This evaluation's provider has no default model. Set a model on the evaluation before enabling it."
                }
            )

    def _missing_key_message(self, team: Team, provider: str | None) -> str:
        """A team with a working key the eval isn't set to use needs to pick it, not add another one."""
        keys = LLMProviderKey.objects.filter(team=team, state=LLMProviderKey.State.OK)
        if provider:
            keys = keys.filter(provider=provider)
        if keys.exists():
            return (
                "This project has a working AI provider API key, but this evaluation isn't set to use it. "
                "Choose that key for the evaluation's model, or make it the project's active key, then enable the evaluation."
            )
        return (
            "LLM judges run on your own AI provider API key, and this project doesn't have a working one yet. "
            "A project admin can add one in Settings > AI observability > Bring your own key (BYOK), "
            "then enable this evaluation."
        )

    def _effective_model_configuration(self, data: dict) -> dict[str, Any] | None:
        """The explicit model configuration the evaluation will have after this update, or None
        when it defers to the team default (null config). Payload presence wins because an explicit
        null is still accepted for legacy null-config evaluations and when switching to a type that
        does not use a model."""
        if "model_configuration" in data:
            return data["model_configuration"]
        if self.instance is not None and self.instance.model_configuration is not None:
            mc = self.instance.model_configuration
            return {
                "provider": mc.provider,
                "model": mc.model,
                "provider_key_id": str(mc.provider_key_id) if mc.provider_key_id else None,
            }
        return None

    def _has_model_configuration_after_update(self, data: dict) -> bool:
        return bool(data.get("model_configuration")) or bool(self.instance and self.instance.model_configuration_id)

    def _effective_provider_key(self, data: dict) -> LLMProviderKey | None:
        """The provider key the evaluation will use after this update. With no pinned key, an
        explicit config falls back to the team's active key for the same provider, mirroring
        `active_key_fallback` in model_resolution.py."""
        team = self.context["get_team"]()
        model_config = self._effective_model_configuration(data)
        if not model_config:
            return None
        provider_key_id = model_config.get("provider_key_id")
        if provider_key_id:
            return LLMProviderKey.objects.filter(id=provider_key_id, team=team).first()
        provider = model_config.get("provider")
        config = EvaluationConfig.objects.filter(team=team).first()
        return active_key_fallback(config, provider) if config and provider else None

    def _create_or_update_model_configuration(
        self, model_config_data: dict[str, Any] | None, team_id: int
    ) -> LLMModelConfiguration | None:
        """Create or update an LLMModelConfiguration from serializer data."""
        if model_config_data is None:
            return None

        provider_key = None
        provider_key_id = model_config_data.get("provider_key_id")
        if provider_key_id:
            try:
                provider_key = LLMProviderKey.objects.get(id=provider_key_id, team_id=team_id)
            except LLMProviderKey.DoesNotExist:
                raise serializers.ValidationError(
                    {"model_configuration": {"provider_key_id": "Provider key not found"}}
                )

        model_config = LLMModelConfiguration(
            team_id=team_id,
            provider=model_config_data["provider"],
            model=model_config_data["model"],
            provider_key=provider_key,
        )
        model_config.full_clean()
        model_config.save()
        return model_config

    def create(self, validated_data):
        request = self.context["request"]
        team = self.context["get_team"]()
        validated_data["team"] = team
        validated_data["created_by"] = request.user

        model_config_data = validated_data.pop("model_configuration", None)
        if model_config_data:
            validated_data["model_configuration"] = self._create_or_update_model_configuration(
                model_config_data, team.id
            )

        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Switching away from an LLM judge uses an explicit null to detach its config; omission leaves it untouched.
        # pop()'s default can't tell the two apart, so check membership explicitly.
        model_config_provided = "model_configuration" in validated_data
        model_config_data = validated_data.pop("model_configuration", None)
        old_config = None

        if model_config_provided:
            # Defer the cascade until after super().update(): SET_NULL would otherwise null
            # Evaluation.model_configuration_id before ModelActivityMixin.save() snapshots
            # before_update from the DB, producing a `null -> new` diff instead of `old -> new`.
            if instance.model_configuration:
                old_config = instance.model_configuration

            validated_data["model_configuration"] = self._create_or_update_model_configuration(
                model_config_data, instance.team_id
            )

        result = super().update(instance, validated_data)

        if old_config is not None:
            old_config.delete()

        return result


class EvaluationFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search", help_text="Search in name or description")
    directory_id = django_filters.UUIDFilter(
        field_name="directory_id",
        help_text="Filter evaluations by directory UUID.",
    )
    directory_id__isnull = django_filters.BooleanFilter(
        field_name="directory_id",
        lookup_expr="isnull",
        help_text="Filter evaluations by whether they are at the top level.",
    )
    enabled = django_filters.BooleanFilter(help_text="Filter by enabled status")
    evaluation_type = django_filters.ChoiceFilter(
        choices=EvaluationType.choices,
        help_text="Filter by evaluation type",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("name", "name"),
        ),
        field_labels={
            "created_at": "Created At",
            "updated_at": "Updated At",
            "name": "Name",
        },
    )

    class Meta:
        model = Evaluation
        fields = {
            "id": ["in"],
            "enabled": ["exact"],
            "evaluation_type": ["exact"],
        }

    def filter_search(self, queryset, name, value):
        if value:
            return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))
        return queryset


class EvaluationListSerializer(EvaluationSerializer):
    """Slim list serializer for MCP callers — drops heavy per-item fields to save tokens.

    Gated on the ``X-PostHog-Client: mcp`` header so the web UI keeps the full shape
    it relies on (see `EvaluationViewSet.get_serializer_class`).
    """

    class Meta(EvaluationSerializer.Meta):
        fields = [
            f
            for f in EvaluationSerializer.Meta.fields
            if f
            not in (
                "evaluation_config",
                "output_config",
                "conditions",
                "model_configuration",
                "created_by",
                "deleted",
            )
        ]
        read_only_fields = [f for f in EvaluationSerializer.Meta.read_only_fields if f != "created_by"]


class PreviewSettleStrategy(models.TextChoices):
    FIXED_WINDOW = "fixed_window", "Fixed window"
    INACTIVITY = "inactivity", "Inactivity"


class TestHogTargetConfigSerializer(serializers.Serializer):
    """The evaluation's own `target_config` works here, so a client sends it as it is."""

    strategy = serializers.ChoiceField(
        choices=PreviewSettleStrategy.choices,
        required=False,
        help_text=(
            "The evaluation's settle strategy. A session evaluation with a fixed window is previewed on "
            "sessions that have been quiet for `window_seconds`, otherwise for `quiet_period_seconds`."
        ),
    )
    window_seconds = serializers.IntegerField(
        required=False,
        min_value=TRACE_EVAL_MIN_WINDOW_SECONDS,
        max_value=SESSION_EVAL_MAX_WINDOW_SECONDS,
        help_text=(
            f"Aggregation window in seconds. A trace preview defaults to {TRACE_EVAL_DEFAULT_WINDOW_SECONDS} "
            f"and uses at most {TRACE_EVAL_MAX_WINDOW_SECONDS}."
        ),
    )
    quiet_period_seconds = serializers.IntegerField(
        required=False,
        min_value=SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS,
        max_value=SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
        help_text=(
            "For session samples: only sessions with no activity for this long are previewed, "
            "matching when a session evaluation would actually run. Defaults to "
            f"{SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS}."
        ),
    )


class HogEvaluationOutputType(models.TextChoices):
    BOOLEAN = OutputType.BOOLEAN.value, OutputType.BOOLEAN.label
    NUMERIC = OutputType.NUMERIC.value, OutputType.NUMERIC.label
    CATEGORICAL = OutputType.CATEGORICAL.value, OutputType.CATEGORICAL.label


OVERVIEW_CACHE_SECONDS = 300


@extend_schema_field(OpenApiTypes.STR)
class _DateOrDateTimeField(serializers.Field):
    """A `YYYY-MM-DD` date for whole days, or an ISO 8601 datetime for an exact instant."""

    def to_internal_value(self, data: Any) -> date | datetime:
        if not isinstance(data, str):
            self.fail("invalid")
        try:
            return date.fromisoformat(data) if len(data) == 10 else datetime.fromisoformat(data)
        except ValueError:
            self.fail("invalid")

    def to_representation(self, value: date | datetime) -> str:
        return value.isoformat()

    default_error_messages = {"invalid": "Enter a date (YYYY-MM-DD) or an ISO 8601 datetime."}


class EvaluationsOverviewPeriodSerializer(serializers.Serializer):
    date_from = _DateOrDateTimeField(
        required=False,
        help_text="Start of the period: a date for the whole day in the project's timezone, or an ISO 8601 datetime. "
        "Defaults to 13 days before `date_to`.",
    )
    date_to = _DateOrDateTimeField(
        required=False,
        help_text="End of the period: a date includes that whole day, a datetime is an exclusive instant. "
        "Defaults to today.",
    )
    refresh = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Skip the result cached for the last five minutes and compute it again.",
    )


class EvaluationsOverviewQuerySerializer(EvaluationsOverviewPeriodSerializer):
    evaluation_ids = RepeatedOrCommaSeparatedListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Only these evaluations. Defaults to every evaluation the user can see.",
    )


class EvaluationRunOutcome(models.TextChoices):
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"


class EvaluationRunsQuerySerializer(EvaluationsOverviewPeriodSerializer):
    outcome = serializers.ChoiceField(
        choices=EvaluationRunOutcome.choices,
        required=False,
        help_text="Only runs with this outcome under the evaluation's passing rule. Without it, every graded run, "
        "including scored, categorized and sentiment runs. An evaluation without a passing rule rejects this filter "
        "with a 400.",
    )
    limit = serializers.IntegerField(
        required=False, default=5, min_value=1, max_value=50, help_text="How many runs to return, newest first."
    )


class PreviewConditionSerializer(EvaluationConditionSerializer):
    """A trigger condition set, as on an evaluation. The id is optional here."""

    id = serializers.CharField(max_length=100, required=False, help_text="Identifier of this condition set, if any.")


class _EvaluationPreviewScopeSerializer(serializers.Serializer):
    """What a preview samples from: the unsaved evaluation's conditions and target."""

    conditions = PreviewConditionSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Optional trigger conditions to filter which events are sampled.",
    )
    target = serializers.ChoiceField(
        choices=EvaluationTarget.choices,
        required=False,
        default=EvaluationTarget.GENERATION,
        help_text=(
            "What the evaluation runs against: 'generation' samples individual generations, "
            "'trace' samples whole traces, and 'session' samples whole sessions that have gone "
            "quiet. Each target runs against the same globals it would run against online."
        ),
    )
    target_config = TestHogTargetConfigSerializer(
        required=False,
        default=dict,
        help_text=(
            "Target-specific preview settings. For a trace target, set window_seconds between "
            f"{TRACE_EVAL_MIN_WINDOW_SECONDS} and {TRACE_EVAL_MAX_WINDOW_SECONDS}."
        ),
    )


class TestHogRequestSerializer(_EvaluationPreviewScopeSerializer):
    output_type = serializers.ChoiceField(
        choices=HogEvaluationOutputType.choices,
        required=False,
        default=OutputType.BOOLEAN,
        help_text="Expected output: boolean, numeric, or categorical. Sentiment is not supported by Hog.",
    )
    output_config = _OutputConfigField(
        required=False,
        default=dict,
        help_text="Output settings used to validate the preview, including bounds, categories, and allows_na.",
    )
    source = serializers.CharField(
        required=True,
        min_length=1,
        help_text=(
            "Hog source code to test. Return a boolean, finite number, or category keys matching output_type. "
            "Categorical single selection accepts one key or a one-item list; multiple selection accepts a list, including []. "
            "Return null only for allowed N/A. "
            "Output settings determine which boolean counts as a failure."
        ),
    )  # type: ignore[assignment]
    sample_count = serializers.IntegerField(
        required=False,
        default=5,
        min_value=1,
        max_value=10,
        help_text="Number of recent $ai_generation events to test against (1–10, default 5).",
    )
    allows_na = serializers.BooleanField(
        required=False, default=False, help_text="Whether the evaluation can return N/A for non-applicable generations."
    )
    sample_ids = serializers.ListField(
        child=serializers.CharField(max_length=400),
        required=False,
        max_length=facade.MAX_PREVIEW_UNITS,
        help_text=(
            "Test exactly these units instead of sampling: generation event UUIDs, trace IDs, or session IDs, "
            f"matching `target`. Up to {facade.MAX_PREVIEW_UNITS}, and only units from the last "
            f"{EVALUATION_TEST_LOOKBACK_DAYS} days. Conditions and sampling are ignored for pinned units, and "
            "unknown IDs are skipped. A session target tests at most "
            f"{SESSION_TEST_HOG_MAX_SAMPLES} sessions."
        ),
    )

    def validate(self, data: dict) -> dict:
        output_config = {"allows_na": data["allows_na"], **data["output_config"]}
        try:
            _, output_config = validate_evaluation_configs(
                "hog", data["output_type"], {"source": data["source"]}, output_config
            )
        except ValueError as error:
            raise serializers.ValidationError({"output_config": str(error)}) from error
        data["output_config"] = output_config
        data["allows_na"] = output_config.get("allows_na", False)
        return data


class PreviewOutcome(models.TextChoices):
    PASS = "pass", "Pass"
    FAIL = "fail", "Fail"
    NA = "na", "Not applicable"
    ERROR = "error", "Error"


class TestHogResultItemSerializer(serializers.Serializer):
    categories = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Selected category keys. An empty list is an applicable result; null means no categorical result was produced.",
    )
    score = serializers.FloatField(
        required=False, allow_null=True, help_text="Raw numeric score, or null when no numeric score was produced."
    )
    sample_id = serializers.CharField(help_text="Stable identifier for the sampled generation, trace, or session.")
    sample_type = serializers.ChoiceField(
        choices=EvaluationTarget.choices,
        help_text="Type of sampled unit: generation, trace, or session.",
    )
    event_uuid = serializers.CharField(
        allow_null=True,
        help_text="UUID of the sampled $ai_generation event, or null for a trace or session sample.",
    )
    trace_id = serializers.CharField(allow_null=True, help_text="Trace ID if available.")
    input_preview = serializers.CharField(help_text="First 200 characters of input from the sampled unit.")
    output_preview = serializers.CharField(help_text="First 200 characters of output from the sampled unit.")
    result = serializers.BooleanField(
        allow_null=True, help_text="Raw boolean result, or null when the evaluation returns N/A or raises an error."
    )
    reasoning = serializers.CharField(allow_null=True, help_text="Hog evaluation reasoning string, if any.")
    error = serializers.CharField(allow_null=True, help_text="Error message if the Hog code raised an exception.")
    outcome = serializers.ChoiceField(
        choices=PreviewOutcome.choices,
        allow_null=True,
        help_text=(
            "How the evaluation's passing rule grades this result: pass, fail, na for a not-applicable result, "
            "or error. Null when there is no rule to grade it, such as a score with no passing rule."
        ),
    )


class TestHogResponseSerializer(serializers.Serializer):
    results = TestHogResultItemSerializer(many=True)
    message = serializers.CharField(
        required=False, help_text="Optional message, e.g. when no recent events were found."
    )


class EvaluationSampleTrafficRequestSerializer(_EvaluationPreviewScopeSerializer):
    count = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=facade.MAX_PREVIEW_UNITS,
        help_text=(
            f"How many units to return, {facade.DEFAULT_PREVIEW_UNITS} by default. Sessions return at most "
            f"{SESSION_TEST_HOG_MAX_SAMPLES}, the number a session test covers."
        ),
    )


class EvaluationSampleTrafficItemSerializer(serializers.Serializer):
    sample_id = serializers.CharField(help_text="Generation event UUID, trace ID, or session ID, matching `target`.")
    sample_type = serializers.ChoiceField(
        choices=EvaluationTarget.choices, help_text="Type of unit: generation, trace, or session."
    )
    trace_id = serializers.CharField(
        allow_null=True,
        help_text="Trace to open for this unit. For a session, its most recent trace. Null when the unit has none.",
    )
    timestamp = serializers.DateTimeField(help_text="When the unit's latest generation happened.")
    input_preview = serializers.CharField(
        help_text="First 200 characters of the last user message in the unit's latest generation."
    )
    output_preview = serializers.CharField(
        help_text="First 200 characters of the last assistant message in the unit's latest generation."
    )


class EvaluationSampleTrafficResponseSerializer(serializers.Serializer):
    results = EvaluationSampleTrafficItemSerializer(many=True)


# Sentiment is not offered: its classifier ships only in the AI observability worker image, not the web image.
class TestOnSampleEvaluationType(models.TextChoices):
    LLM_JUDGE = EvaluationType.LLM_JUDGE.value, EvaluationType.LLM_JUDGE.label


class EvaluationTestOnSampleRequestSerializer(_EvaluationPreviewScopeSerializer):
    evaluation_type = serializers.ChoiceField(
        choices=TestOnSampleEvaluationType.choices,
        help_text="'llm_judge' runs the judge, or the decision model, on your own provider key.",
    )
    evaluation_config = _EvaluationConfigField(
        help_text="Same as on an evaluation: {prompt, judge_method}.",
    )
    model_configuration = ModelConfigurationSerializer(
        required=False,
        allow_null=True,
        help_text="Provider and model for an llm_judge, as on an evaluation. Required for llm_judge.",
    )
    output_type = serializers.ChoiceField(
        choices=OutputType.choices,
        required=False,
        default=OutputType.BOOLEAN,
        help_text="Expected output: boolean, numeric, or categorical.",
    )
    output_config = _OutputConfigField(
        required=False,
        default=dict,
        help_text="Output settings, as on an evaluation: bounds, categories, allows_na, and passing rules.",
    )
    sample_ids = serializers.ListField(
        child=serializers.CharField(max_length=400),
        required=False,
        max_length=facade.MAX_JUDGE_TEST_UNITS,
        help_text=(
            f"Test exactly these units instead of sampling, up to {facade.MAX_JUDGE_TEST_UNITS}: generation event "
            "UUIDs, trace IDs, or session IDs, matching `target`. Conditions are ignored for pinned units, and "
            "unknown IDs are skipped."
        ),
    )


def _preview_settle(target_config: Mapping[str, Any]) -> contracts.EvaluationPreviewSettle:
    return contracts.EvaluationPreviewSettle(
        strategy=target_config.get("strategy"),
        window_seconds=target_config.get("window_seconds"),
        quiet_period_seconds=target_config.get("quiet_period_seconds"),
    )


def _preview_scope(data: Mapping[str, Any]) -> contracts.EvaluationPreviewScope:
    return contracts.EvaluationPreviewScope(
        target=data["target"], conditions=data["conditions"], settle=_preview_settle(data["target_config"])
    )


def _hog_test_row_counts(results: Sequence[Mapping[str, object]]) -> dict[str, int]:
    return outcome_counts(cast("contracts.PreviewOutcome | None", result["outcome"]) for result in results)


def _humanize_seconds(seconds: int) -> str:
    """Whole units only: this reads back the quiet period the user just set, so "24 hours" beats
    "1440 minutes"."""
    if seconds >= 3600 and seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    if seconds >= 60:
        minutes = seconds // 60
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    return f"{seconds} second" if seconds == 1 else f"{seconds} seconds"


def _test_hog_over_sessions(
    *,
    request: Request,
    team: Team,
    bytecode: list[Any],
    condition_filter: ast.Expr | None,
    sample_count: int,
    allows_na: bool,
    conditions: list[dict[str, Any]],
    quiet_period_seconds: int,
    output_type: str = "boolean",
    output_config: dict | None = None,
    sample_ids: Sequence[str] | None = None,
) -> Response:
    """Session-target variant of `test_hog`: sample sessions that have gone quiet and run the code
    against session-level globals, so the editor preview matches how a session eval runs online."""
    tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
    try:
        session_results = run_hog_eval_over_recent_sessions(
            team=team,
            user=cast("User", request.user),
            bytecode=bytecode,
            condition_filter=condition_filter,
            sample_count=sample_count,
            allows_na=allows_na,
            output_type=output_type,
            output_config=output_config,
            quiet_period_seconds=quiet_period_seconds,
            sample_ids=sample_ids,
        )
    except AIEventsUnavailableError:
        session_results = []

    grader = preview_grader(output_type, output_config)
    results = [
        {
            "sample_id": r.session_id,
            "sample_type": EvaluationTarget.SESSION.value,
            "event_uuid": None,
            "trace_id": None,
            "input_preview": r.input_preview,
            "output_preview": r.output_preview,
            "result": r.verdict,
            **({"score": r.score} if output_type == "numeric" else {}),
            **({"categories": r.categories} if output_type == "categorical" else {}),
            "reasoning": r.reasoning,
            "error": r.error,
            "outcome": grader.outcome(error=r.error, result=r.verdict, score=r.score, categories=r.categories),
        }
        for r in session_results
    ]

    report_user_action(
        request.user,
        "llma evaluation hog code tested",
        {
            "sample_count": sample_count,
            "results_count": len(results),
            **_hog_test_row_counts(results),
            "target": EvaluationTarget.SESSION.value,
            "condition_count": len(conditions),
        },
        team=team,
        request=request,
    )

    if not results:
        # An empty sample here is a real answer, not a failure: at a long quiet period there may
        # genuinely be no settled session yet. Say which window came up empty so it does not
        # read as broken.
        return Response(
            {
                "results": [],
                "message": (
                    f"No sessions have been quiet for {_humanize_seconds(quiet_period_seconds)} in the last "
                    f"{EVALUATION_TEST_LOOKBACK_DAYS} days, so there is nothing to preview yet."
                ),
            }
        )
    return Response({"results": results})


def _test_hog_over_traces(
    *,
    request: Request,
    team: Team,
    bytecode: list[Any],
    condition_filter: ast.Expr | None,
    sample_count: int,
    allows_na: bool,
    conditions: list[dict[str, Any]],
    window_seconds: int,
    output_type: str = "boolean",
    output_config: dict | None = None,
    sample_ids: Sequence[str] | None = None,
) -> Response:
    """Trace-target variant of the `test_hog` action: sample recent whole traces and run the code
    against trace-level globals, so the editor preview matches how a trace eval runs online."""
    tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
    try:
        trace_results = run_hog_eval_over_recent_traces(
            team=team,
            user=cast("User", request.user),
            bytecode=bytecode,
            condition_filter=condition_filter,
            sample_count=sample_count,
            allows_na=allows_na,
            output_type=output_type,
            output_config=output_config,
            window_seconds=window_seconds,
            sample_ids=sample_ids,
        )
    except AIEventsUnavailableError:
        trace_results = []

    grader = preview_grader(output_type, output_config)
    results = [
        {
            "sample_id": r.trace_id,
            "sample_type": EvaluationTarget.TRACE.value,
            "event_uuid": None,
            "trace_id": r.trace_id,
            "input_preview": r.input_preview,
            "output_preview": r.output_preview,
            "result": r.verdict,
            **({"score": r.score} if output_type == "numeric" else {}),
            **({"categories": r.categories} if output_type == "categorical" else {}),
            "reasoning": r.reasoning,
            "error": r.error,
            "outcome": grader.outcome(error=r.error, result=r.verdict, score=r.score, categories=r.categories),
        }
        for r in trace_results
    ]

    report_user_action(
        request.user,
        "llma evaluation hog code tested",
        {
            "sample_count": sample_count,
            "allows_na": allows_na,
            "condition_count": len(conditions),
            "result_count": len(results),
            **_hog_test_row_counts(results),
            "no_events": not results,
            "target": EvaluationTarget.TRACE.value,
        },
        team=team,
        request=request,
    )

    if not results:
        return Response(
            {
                "results": [],
                "message": f"No recent AI traces found in the last {EVALUATION_TEST_LOOKBACK_DAYS} days",
            }
        )
    return Response({"results": results})


def _test_hog_over_generations(
    *,
    request: Request,
    team: Team,
    bytecode: list[Any],
    condition_filter: ast.Expr | None,
    sample_count: int,
    allows_na: bool,
    conditions: list[dict[str, Any]],
    output_type: str = "boolean",
    output_config: dict | None = None,
    sample_ids: Sequence[str] | None = None,
) -> Response:
    """Generation-target variant of the `test_hog` action: run the code against recent generations."""
    tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
    try:
        events = load_generation_events(
            team,
            cast("User", request.user),
            condition_filter=condition_filter,
            sample_count=sample_count,
            sample_ids=sample_ids,
        )
    except AIEventsUnavailableError:
        events = []

    grader = preview_grader(output_type, output_config)
    results = []
    for event_data in events:
        result = run_hog_eval(
            bytecode, event_data, allows_na=allows_na, output_type=output_type, output_config=output_config
        )
        io_preview = generation_io_preview(event_data)
        results.append(
            {
                "sample_id": event_data["uuid"],
                "sample_type": EvaluationTarget.GENERATION.value,
                "event_uuid": event_data["uuid"],
                "trace_id": event_data["properties"].get("$ai_trace_id"),
                "input_preview": io_preview.input,
                "output_preview": io_preview.output,
                "result": result.get("verdict"),
                **({"score": result.get("score")} if output_type == "numeric" else {}),
                **({"categories": result.get("categories")} if output_type == "categorical" else {}),
                "reasoning": result["reasoning"],
                "error": result["error"],
                "outcome": grader.outcome(
                    error=result["error"],
                    result=result.get("verdict"),
                    score=result.get("score"),
                    categories=result.get("categories"),
                ),
            }
        )

    report_user_action(
        request.user,
        "llma evaluation hog code tested",
        {
            "sample_count": sample_count,
            "allows_na": allows_na,
            "condition_count": len(conditions),
            "result_count": len(results),
            **_hog_test_row_counts(results),
            "no_events": not results,
            "target": EvaluationTarget.GENERATION.value,
        },
        team=team,
        request=request,
    )

    if not results:
        return Response(
            {
                "results": [],
                "message": f"No recent AI events found in the last {EVALUATION_TEST_LOOKBACK_DAYS} days",
            }
        )
    return Response({"results": results})


def _config_length(instance: Evaluation) -> int:
    """Get the relevant config content length for tracking."""
    if instance.evaluation_config and isinstance(instance.evaluation_config, dict):
        content_key = get_evaluation_config_content_key(instance.evaluation_type)
        content = instance.evaluation_config.get(content_key, "") if content_key else ""
        return len(content) if isinstance(content, str) else 0
    return 0


def create_evaluation(
    serializer: EvaluationSerializer,
    *,
    request: Request,
    team: Team,
    tracking_properties: Mapping[str, Any] | None = None,
) -> Evaluation:
    """Save a validated evaluation with its default report and track the creation."""
    with transaction.atomic():
        instance = serializer.save()

        if evaluation_supports_reports(instance.output_type, instance.target, instance.output_config):
            # Auto-create a default report config so reports are generated from the start.
            # Defaults to count-triggered (frequency=every_n), so rrule/starts_at stay empty
            # and users add email/Slack delivery targets later if they want notifications.
            EvaluationReport.objects.get_or_create(evaluation=instance, team_id=team.id)

    conditions = instance.conditions or []
    report_user_action(
        request.user,
        "llma evaluation created",
        {
            "evaluation_id": str(instance.id),
            "evaluation_name": instance.name,
            "evaluation_type": instance.evaluation_type,
            "output_type": instance.output_type,
            "has_description": bool(instance.description),
            "enabled": instance.enabled,
            "condition_count": len(conditions),
            "has_rollout_percentage": any(condition.get("rollout_percentage", 100) < 100 for condition in conditions),
            **(tracking_properties or {}),
            "config_length": _config_length(instance),
        },
        team=team,
        request=request,
    )
    return instance


class EvaluationViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "evaluation"
    permission_classes = [IsAuthenticated, AccessControlPermission]
    serializer_class = EvaluationSerializer
    queryset = Evaluation.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = EvaluationFilter

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "test_on_sample":
            return [
                *super().get_throttles(),
                AIObservabilityEvaluationJudgeTestThrottle(),
                AIObservabilityEvaluationJudgeTestTeamThrottle(),
            ]
        return super().get_throttles()

    @staticmethod
    def _is_mcp_request(request: Request) -> bool:
        return request.META.get("HTTP_X_POSTHOG_CLIENT") == "mcp"

    def _wants_slim_list(self) -> bool:
        return self.action == "list" and self._is_mcp_request(self.request)

    def get_serializer_class(self):
        if self._wants_slim_list():
            return EvaluationListSerializer
        return super().get_serializer_class()

    def safely_get_queryset(self, queryset: QuerySet[Evaluation]) -> QuerySet[Evaluation]:
        queryset = queryset.filter(team_id=self.team_id).order_by("-created_at", "id")
        if not self._wants_slim_list():
            queryset = queryset.select_related("created_by", "model_configuration", "model_configuration__provider_key")
        if not self.action.endswith("update"):
            queryset = queryset.filter(deleted=False)
        return queryset

    def safely_get_object(self, queryset: QuerySet[Evaluation]) -> Evaluation:
        evaluation_id = self.kwargs["pk"]
        try:
            # Matches what DRF's own get_object() does, including coercing an unparseable pk to a
            # 404, so only the message differs.
            return get_object_or_404(queryset, pk=evaluation_id)
        except Http404:
            # DRF's bare "Not found." points a caller at nothing it can act on. A name passed where
            # the id belongs lands here too, since it can't parse as a UUID.
            raise NotFound(
                f"No evaluation '{evaluation_id}' in this project. "
                "List the project's evaluations to look one up by name."
            )

    def perform_create(self, serializer):
        create_evaluation(serializer, request=self.request, team=self.team)

    def perform_update(self, serializer):
        previously_supported_reports = evaluation_supports_reports(
            serializer.instance.output_type, serializer.instance.target, serializer.instance.output_config
        )
        # Check if this is a deletion (soft delete)
        is_deletion = serializer.validated_data.get("deleted") is True and not serializer.instance.deleted

        # Capture old enabled state before save (for deletion tracking)
        old_enabled_value = serializer.instance.enabled

        # Track changes before update
        changed_fields: list[str] = []
        enabled_changed = False
        enabled_new_value = None
        condition_count_changed = False
        condition_count_new = 0
        config_content_changed = False

        for field in [
            "name",
            "description",
            "directory",
            "enabled",
            "evaluation_type",
            "output_type",
            "evaluation_config",
            "output_config",
            "conditions",
            "deleted",
        ]:
            if field in serializer.validated_data:
                old_value = getattr(serializer.instance, field)
                new_value = serializer.validated_data[field]
                if old_value != new_value:
                    changed_fields.append(field)

                    if field == "enabled":
                        enabled_changed = True
                        enabled_new_value = new_value
                    elif field == "conditions":
                        condition_count_changed = True
                        condition_count_new = len(new_value) if new_value else 0
                    elif field == "evaluation_config":
                        eval_type = serializer.validated_data.get(
                            "evaluation_type", serializer.instance.evaluation_type
                        )
                        config_key = get_evaluation_config_content_key(eval_type)
                        old_content = (
                            old_value.get(config_key, "") if config_key and isinstance(old_value, dict) else ""
                        )
                        new_content = (
                            new_value.get(config_key, "") if config_key and isinstance(new_value, dict) else ""
                        )
                        if old_content != new_content:
                            config_content_changed = True

        with transaction.atomic():
            instance = serializer.save()
            if (
                not previously_supported_reports
                and not instance.deleted
                and evaluation_supports_reports(instance.output_type, instance.target, instance.output_config)
            ):
                report, created = EvaluationReport.objects.get_or_create(evaluation=instance, team_id=self.team_id)
                if not created:
                    report.restart_reporting()

        # Track appropriate event
        if is_deletion:
            report_user_action(
                self.request.user,
                "llma evaluation deleted",
                {
                    "evaluation_id": str(instance.id),
                    "evaluation_name": instance.name,
                    "was_enabled": old_enabled_value,
                },
                team=self.team,
                request=self.request,
            )
        elif changed_fields:
            event_properties: dict[str, Any] = {
                "evaluation_id": str(instance.id),
                "changed_fields": changed_fields,
            }

            if enabled_changed:
                event_properties["enabled_changed"] = True
                event_properties["enabled_new_value"] = enabled_new_value
            if condition_count_changed:
                event_properties["condition_count_changed"] = True
                event_properties["condition_count_new"] = condition_count_new
            if config_content_changed:
                event_properties["config_content_changed"] = True

            report_user_action(
                self.request.user,
                "llma evaluation updated",
                event_properties,
                team=self.team,
                request=self.request,
            )

    @llma_track_latency("llma_evaluations_list")
    @monitor(feature=None, endpoint="llma_evaluations_list", method="GET")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_retrieve")
    @monitor(feature=None, endpoint="llma_evaluations_retrieve", method="GET")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_create")
    @monitor(feature=None, endpoint="llma_evaluations_create", method="POST")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_update")
    @monitor(feature=None, endpoint="llma_evaluations_update", method="PUT")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @llma_track_latency("llma_evaluations_partial_update")
    @monitor(feature=None, endpoint="llma_evaluations_partial_update", method="PATCH")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    def _overview_period(self, request: ValidatedRequest) -> "PeriodBounds":
        query = request.validated_query_data
        try:
            return facade.evaluations_period(self.team, query.get("date_from"), query.get("date_to"))
        except facade.InvalidPeriodError as error:
            raise serializers.ValidationError({error.field: str(error)} if error.field else str(error))

    def _cached_overview_read(
        self,
        request: ValidatedRequest,
        name: str,
        evaluation_ids: Sequence[str],
        period: "PeriodBounds",
        read: Callable[[], Contract],
    ) -> Response:
        # Keyed by the evaluations the user can see and by their current property restrictions, because a hit skips
        # the masking a fresh read applies, and a restriction can change while an entry is still cached.
        visible = hashlib.sha256(",".join(sorted(evaluation_ids)).encode()).hexdigest()
        restrictions = restriction_fingerprint(
            get_restricted_properties_with_group_type_index_for_team(
                user=cast("User", request.user), team_id=self.team.pk
            )
        )
        cache_key = (
            f"ai_evaluations_{name}/{self.team.pk}/{request.user.pk}/{period.start.astimezone(UTC).isoformat()}/{period.end.astimezone(UTC).isoformat()}"
            f"/{visible}/{restrictions}"
        )
        if not request.validated_query_data["refresh"]:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)
        tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
        with query_concurrency_slots(self.team):
            payload = read().model_dump(mode="json", by_alias=True)
        cache.set(cache_key, payload, timeout=OVERVIEW_CACHE_SECONDS)
        return Response(payload)

    @validated_request(
        query_serializer=EvaluationsOverviewQuerySerializer,
        responses={
            200: OpenApiResponse(response=contracts.EvaluationsOverview),
            400: OpenApiResponse(description="The period is malformed, empty, longer than 91 days or out of range."),
            429: OpenApiResponse(description="Too many queries are running for the project or organization."),
        },
    )
    @action(detail=False, methods=["get"], url_path="overview", required_scopes=["evaluation:read"])
    def overview(self, request: ValidatedRequest, **kwargs) -> Response:
        """Each evaluation's results over a period, compared with the period of equal length before it."""
        period = self._overview_period(request)
        queryset = self.get_queryset()
        # The base viewset narrows by access level on `list` only, so this read applies it itself.
        if not is_service_auth(request):
            queryset = self.user_access_control.filter_queryset_by_access_level(queryset)
        query = request.validated_query_data
        if "evaluation_ids" in query:
            queryset = queryset.filter(id__in=query["evaluation_ids"])
        evaluation_ids = [str(evaluation_id) for evaluation_id in queryset.values_list("id", flat=True)]
        return self._cached_overview_read(
            request,
            "overview",
            evaluation_ids,
            period,
            lambda: facade.get_evaluations_overview(self.team, cast("User", request.user), evaluation_ids, period),
        )

    @validated_request(
        query_serializer=EvaluationRunsQuerySerializer,
        responses={
            200: OpenApiResponse(response=contracts.EvaluationRuns),
            400: OpenApiResponse(
                description="The period is invalid, or an outcome filter is set on an evaluation without a passing rule."
            ),
            429: OpenApiResponse(description="Too many queries are running for the project or organization."),
        },
    )
    @action(detail=True, methods=["get"], url_path="runs", required_scopes=["evaluation:read"])
    def runs(self, request: ValidatedRequest, **kwargs) -> Response:
        """One evaluation's latest graded runs in a period, newest first, optionally only the passed or failed ones."""
        evaluation_id = str(self.get_object().id)
        period = self._overview_period(request)
        query = request.validated_query_data
        outcome, limit = query.get("outcome"), query["limit"]
        try:
            return self._cached_overview_read(
                request,
                f"runs/{outcome}/{limit}",
                [evaluation_id],
                period,
                lambda: facade.get_evaluation_runs(
                    self.team, cast("User", request.user), evaluation_id, period, outcome, limit
                ),
            )
        except facade.NoPassingRuleError:
            raise serializers.ValidationError(
                {"outcome": "This evaluation has no passing rule, so its runs are neither passed nor failed."}
            )

    @validated_request(
        query_serializer=EvaluationsOverviewPeriodSerializer,
        responses={
            200: OpenApiResponse(response=contracts.ScoreHistogram),
            400: OpenApiResponse(
                description="The period is invalid, or the evaluation is not numeric with a minimum and maximum score."
            ),
            429: OpenApiResponse(description="Too many queries are running for the project or organization."),
        },
    )
    @action(detail=True, methods=["get"], url_path="score_distribution", required_scopes=["evaluation:read"])
    def score_distribution(self, request: ValidatedRequest, **kwargs) -> Response:
        """How one numeric evaluation's scores in a period spread across its configured scale."""
        evaluation_id = str(self.get_object().id)
        period = self._overview_period(request)
        try:
            return self._cached_overview_read(
                request,
                "score_distribution",
                [evaluation_id],
                period,
                lambda: facade.get_evaluation_score_distribution(
                    self.team, cast("User", request.user), evaluation_id, period
                ),
            )
        except facade.NoScoreScaleError:
            raise serializers.ValidationError(
                "Only a numeric evaluation with a minimum and a maximum score has a score distribution."
            )

    @extend_schema(request=TestHogRequestSerializer, responses=TestHogResponseSerializer)
    @action(detail=False, methods=["post"], url_path="test_hog", required_scopes=["evaluation:read"])
    def test_hog(self, request: Request, **kwargs) -> Response:
        """Test Hog evaluation code against sample events without saving."""
        if not self.user_access_control.check_access_level_for_resource("evaluation", "viewer"):
            raise exceptions.PermissionDenied()

        serializer = TestHogRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)

        source = serializer.validated_data["source"]
        sample_count = serializer.validated_data["sample_count"]
        allows_na = serializer.validated_data["allows_na"]
        output_type = serializer.validated_data["output_type"]
        output_config = serializer.validated_data["output_config"]
        conditions = serializer.validated_data.get("conditions", [])
        target = serializer.validated_data["target"]
        target_config = serializer.validated_data["target_config"]
        sample_ids = serializer.validated_data.get("sample_ids") or None

        try:
            bytecode = compile_ai_observability_hog(source, "destination")
        except serializers.ValidationError as e:
            # The code lets the editor tell code that does not compile from a request that failed for another reason.
            return Response({"error": hog_compile_error_message(source, e), "code": "hog_compile_error"}, status=400)
        except Exception:
            logger.exception("Unexpected error compiling Hog source")
            return Response({"error": "Compilation failed due to an unexpected error"}, status=400)

        team = Team.objects.get(id=self.team_id)
        settle = _preview_settle(target_config)

        # Both targets reuse it; for traces it filters which triggering generation qualifies.
        condition_filter = build_condition_filter(conditions, team)

        # The editor runs this on every pause in typing, so it holds the slots a query runner holds.
        with query_concurrency_slots(team):
            if target == EvaluationTarget.SESSION.value:
                return _test_hog_over_sessions(
                    request=request,
                    team=team,
                    bytecode=bytecode,
                    condition_filter=condition_filter,
                    sample_count=min(sample_count, SESSION_TEST_HOG_MAX_SAMPLES),
                    allows_na=allows_na,
                    output_type=output_type,
                    output_config=output_config,
                    conditions=conditions,
                    quiet_period_seconds=session_quiet_period_seconds(settle),
                    # Each session is a whole conversation, so pinned sessions share the sampled cap.
                    sample_ids=sample_ids[:SESSION_TEST_HOG_MAX_SAMPLES] if sample_ids else None,
                )

            if target == EvaluationTarget.TRACE.value:
                return _test_hog_over_traces(
                    request=request,
                    team=team,
                    bytecode=bytecode,
                    condition_filter=condition_filter,
                    sample_count=sample_count,
                    allows_na=allows_na,
                    output_type=output_type,
                    output_config=output_config,
                    conditions=conditions,
                    window_seconds=trace_window_seconds(settle),
                    sample_ids=sample_ids,
                )

            return _test_hog_over_generations(
                request=request,
                team=team,
                bytecode=bytecode,
                condition_filter=condition_filter,
                sample_count=sample_count,
                allows_na=allows_na,
                output_type=output_type,
                output_config=output_config,
                conditions=conditions,
                sample_ids=sample_ids,
            )

    @validated_request(
        request_serializer=EvaluationSampleTrafficRequestSerializer,
        responses={
            200: OpenApiResponse(response=EvaluationSampleTrafficResponseSerializer),
            429: OpenApiResponse(description="Too many queries are running for the project or organization."),
        },
    )
    @action(detail=False, methods=["post"], url_path="sample_traffic", required_scopes=["evaluation:read"])
    def sample_traffic(self, request: ValidatedRequest, **kwargs) -> Response:
        """The latest units an unsaved evaluation would run on, newest first."""
        if not self.user_access_control.check_access_level_for_resource("evaluation", "viewer"):
            raise exceptions.PermissionDenied()

        data = request.validated_data
        tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
        with query_concurrency_slots(self.team):
            samples = facade.sample_evaluation_traffic(
                self.team, cast("User", request.user), _preview_scope(data), data.get("count")
            )
        return Response(EvaluationSampleTrafficResponseSerializer({"results": samples}).data)

    @validated_request(
        request_serializer=EvaluationTestOnSampleRequestSerializer,
        responses={
            200: OpenApiResponse(response=TestHogResponseSerializer),
            429: OpenApiResponse(
                description="This user already has a test running, or too many queries are running for the project."
            ),
        },
    )
    @action(detail=False, methods=["post"], url_path="test_on_sample", required_scopes=["evaluation:write"])
    def test_on_sample(self, request: ValidatedRequest, **kwargs) -> Response:
        """Run an unsaved LLM judge on a few samples. Saves nothing and emits no results."""
        # Each call spends the team's own provider key, so it takes the access that saving an evaluation does.
        if not self.user_access_control.check_access_level_for_resource("evaluation", "editor"):
            raise exceptions.PermissionDenied()

        data = request.validated_data
        # The create path's validation, so a test accepts exactly what saving would.
        evaluation_serializer = EvaluationSerializer(
            data={
                "name": "Unsaved evaluation",
                "evaluation_type": data["evaluation_type"],
                "evaluation_config": data["evaluation_config"],
                "output_type": data["output_type"],
                "output_config": data["output_config"],
                "target": data["target"],
                "model_configuration": data.get("model_configuration"),
            },
            context=self.get_serializer_context(),
        )
        evaluation_serializer.is_valid(raise_exception=True)
        validated = evaluation_serializer.validated_data
        model = validated.get("model_configuration")
        judge = contracts.UnsavedJudge(
            evaluation_config=validated["evaluation_config"],
            output_type=data["output_type"],
            output_config=validated["output_config"],
            model=contracts.JudgeModel(
                provider=model["provider"],
                model=model["model"],
                provider_key_id=str(model["provider_key_id"]) if model.get("provider_key_id") else None,
            )
            if model
            else None,
        )
        sample_ids = data.get("sample_ids") or None
        team = self.team

        tag_queries(product=Product.LLM_ANALYTICS, feature=Feature.QUERY)
        try:
            results = facade.run_unsaved_judge(
                team,
                cast("User", request.user),
                judge,
                _preview_scope(data),
                sample_ids,
                # The slots cover each read, not the model calls between them.
                reading=lambda: query_concurrency_slots(team),
            )
        except contracts.JudgeModelError as error:
            raise serializers.ValidationError({"model_configuration": str(error)})
        except contracts.JudgeTestAlreadyRunningError:
            raise exceptions.Throttled(detail="A test is already running. Wait for it to finish, then try again.")

        report_user_action(
            request.user,
            "llma evaluation tested on sample",
            {
                "evaluation_type": data["evaluation_type"],
                "output_type": data["output_type"],
                "target": data["target"],
                "sample_count": len(results),
                "pinned": sample_ids is not None,
                "condition_count": len(data["conditions"]),
                **outcome_counts(result.outcome for result in results),
            },
            team=team,
            request=request,
        )

        response: dict[str, Any] = {"results": results}
        if not results:
            response["message"] = f"Nothing to test on from the last {EVALUATION_TEST_LOOKBACK_DAYS} days."
        return Response(TestHogResponseSerializer(response).data)
