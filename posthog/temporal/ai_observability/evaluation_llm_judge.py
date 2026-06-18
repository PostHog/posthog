import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone

import structlog
import temporalio
import posthoganalytics
from pydantic import BaseModel, model_validator
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io, extract_event_tools
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.message_utils import extract_text_from_messages, format_tool_definitions
from posthog.temporal.ai_observability.metrics import (
    increment_errors,
    increment_key_type,
    increment_provider_model,
    increment_tokens,
)

from products.ai_observability.backend.llm import TRIAL_MODEL_IDS, Client, CompletionRequest
from products.ai_observability.backend.llm.config import get_eval_config
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ModelNotFoundError,
    ModelPermissionError,
    QuotaExceededError,
    RateLimitError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.provider_keys import LLMProviderKey

logger = structlog.get_logger(__name__)

DEFAULT_JUDGE_MODEL = "gpt-5-mini"

LLM_JUDGE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
)


class BooleanEvalResult(BaseModel):
    """Structured output for boolean evaluation results"""

    reasoning: str
    verdict: bool


class BooleanWithNAEvalResult(BaseModel):
    """Structured output for boolean with N/A evaluation results.

    When the evaluation criteria doesn't apply to the input/output,
    applicable should be False and verdict should be None.
    """

    reasoning: str
    applicable: bool
    verdict: bool | None = None

    @model_validator(mode="after")
    def validate_verdict_consistency(self) -> "BooleanWithNAEvalResult":
        if self.applicable and self.verdict is None:
            raise ValueError("verdict is required when applicable is true")
        if not self.applicable and self.verdict is not None:
            raise ValueError("verdict must be null when applicable is false")
        return self


@dataclass
class OutputTypeConfig:
    """Configuration for each evaluation output type"""

    response_format: type[BooleanEvalResult] | type[BooleanWithNAEvalResult]
    instructions: str


def get_output_type_config(allows_na: bool) -> OutputTypeConfig:
    """Get the output type configuration based on whether N/A is allowed."""
    if allows_na:
        return OutputTypeConfig(
            response_format=BooleanWithNAEvalResult,
            instructions="""First, determine if this evaluation criteria is applicable to the given input/output. If the criteria doesn't apply to this case mark it as not applicable.

Note: If the criteria above instructs you to return "N/A", "not applicable", or similar, treat that as applicable=false with verdict=null.

Return:
- applicable: true if the criteria applies to this input/output, false if it doesn't apply
- verdict: true if it passes, false if it fails, or null if not applicable
- reasoning: a brief explanation (1 sentence)""",
        )
    return OutputTypeConfig(
        response_format=BooleanEvalResult,
        instructions="Provide a brief reasoning (1 sentence) and a boolean verdict (true/false).",
    )


def build_system_prompt(prompt: str, allows_na: bool) -> str:
    """Build the system prompt for the LLM judge."""
    config = get_output_type_config(allows_na)
    return f"""You are an evaluator. Evaluate the following generation according to this criteria:

{prompt}

{config.instructions}"""


@dataclass
class ExecuteLLMJudgeInputs:
    evaluation: dict[str, Any]
    event_data: dict[str, Any]

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.evaluation.get("team_id"),
            "evaluation_id": self.evaluation.get("id"),
        }


def _is_errored_trace(properties: dict[str, Any]) -> bool:
    """Return True when the captured trace recorded an error.

    `$ai_is_error` may be ingested as a Python bool or a JSON-encoded string depending on the
    SDK and capture path, so we normalise both forms here.
    """
    raw = properties.get("$ai_is_error")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() == "true"
    return False


def _build_errored_trace_result(allows_na: bool) -> EvaluationActivityResult:
    """Result returned when the source trace errored — skips the LLM call entirely.

    `model` and `provider` are deliberately omitted so the `.get(..., DEFAULT_JUDGE_MODEL)`
    defaults in downstream activities don't silently attribute phantom calls to a model that
    was never invoked — the emit activity instead detects the `skipped` flag and drops cost
    and model attribution entirely. The `EvaluationActivityResult` TypedDict expresses the shape
    contract previously enforced by convention.
    """
    reasoning = "Source trace errored before producing output; evaluation skipped."
    result: EvaluationActivityResult = {
        "result_type": "boolean",
        "verdict": None if allows_na else False,
        "reasoning": reasoning,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "is_byok": False,
        "key_id": None,
        "allows_na": allows_na,
        "skipped": True,
        "skip_reason": "trace_errored",
    }
    if allows_na:
        result["applicable"] = False
    return result


@temporalio.activity.defn
@posthoganalytics.scoped()
def execute_llm_judge_activity(inputs: ExecuteLLMJudgeInputs) -> EvaluationActivityResult:
    """Execute LLM judge to evaluate the target event.

    Fetches API key configuration internally to avoid passing sensitive data between activities.
    """
    return _execute_llm_judge_activity(inputs)


def _execute_llm_judge_activity(inputs: ExecuteLLMJudgeInputs) -> EvaluationActivityResult:
    evaluation = inputs.evaluation
    event_data = inputs.event_data

    if evaluation["evaluation_type"] != "llm_judge":
        raise ApplicationError(
            f"Unsupported evaluation type: {evaluation['evaluation_type']}",
            non_retryable=True,
        )

    evaluation_config = evaluation.get("evaluation_config", {})
    prompt = evaluation_config.get("prompt")
    if not prompt:
        raise ApplicationError("Missing prompt in evaluation_config", non_retryable=True)

    output_type = evaluation["output_type"]
    if output_type != "boolean":
        raise ApplicationError(
            f"Unsupported output type: {output_type}. Supported types: 'boolean'.",
            non_retryable=True,
        )

    output_config = evaluation.get("output_config", {})
    allows_na = output_config.get("allows_na", False)

    event_type = event_data["event"]
    properties = event_data["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    if _is_errored_trace(properties):
        return _build_errored_trace_result(allows_na)

    team_id = evaluation["team_id"]
    model_configuration = evaluation.get("model_configuration")

    def _get_legacy_provider_key() -> LLMProviderKey | None:
        config, _ = EvaluationConfig.objects.get_or_create(team_id=team_id)

        if config.active_provider_key:
            key = config.active_provider_key
            if key.state == LLMProviderKey.State.OK:
                key.last_used_at = timezone.now()
                key.save(update_fields=["last_used_at"])
                return key
            raise ApplicationError(
                f"This API key has been disabled (status: {key.state}). Re-validate to recover, or replace it.",
                {"error_type": "key_invalid", "key_id": str(key.id), "key_state": key.state},
                non_retryable=True,
            )

        if config.trial_evals_used >= config.trial_eval_limit:
            raise ApplicationError(
                f"Trial evaluation limit ({config.trial_eval_limit}) reached. Add your own API key to continue.",
                {"error_type": "trial_limit_reached", "trial_eval_limit": config.trial_eval_limit},
                non_retryable=True,
            )

        return None

    def _get_provider_key_by_id(key_id: str) -> LLMProviderKey:
        try:
            key = LLMProviderKey.objects.get(id=key_id, team_id=team_id)
            if key.state != LLMProviderKey.State.OK:
                raise ApplicationError(
                    f"This API key has been disabled (status: {key.state}). Re-validate to recover, or replace it.",
                    {"error_type": "key_invalid", "key_id": str(key.id), "key_state": key.state},
                    non_retryable=True,
                )
            key.last_used_at = timezone.now()
            key.save(update_fields=["last_used_at"])
            return key
        except LLMProviderKey.DoesNotExist:
            raise ApplicationError(
                "Provider key not found.",
                {"error_type": "key_not_found", "key_id": key_id},
                non_retryable=True,
            )

    def _check_trial_quota() -> None:
        config, _ = EvaluationConfig.objects.get_or_create(team_id=team_id)
        if config.trial_evals_used >= config.trial_eval_limit:
            raise ApplicationError(
                f"Trial evaluation limit ({config.trial_eval_limit}) reached. Add your own API key to continue.",
                {"error_type": "trial_limit_reached", "trial_eval_limit": config.trial_eval_limit},
                non_retryable=True,
            )

    if model_configuration:
        provider = model_configuration["provider"]
        model = model_configuration["model"]
        provider_key_id = model_configuration.get("provider_key_id")

        if provider_key_id:
            provider_key = _get_provider_key_by_id(provider_key_id)
        else:
            if model not in TRIAL_MODEL_IDS:
                raise ApplicationError(
                    f"Model '{model}' is not available on the trial plan. Please add your own API key to use this model.",
                    {"error_type": "model_not_allowed", "model": model},
                    non_retryable=True,
                )
            _check_trial_quota()
            provider_key = None
    else:
        provider = "openai"
        model = DEFAULT_JUDGE_MODEL
        provider_key = _get_legacy_provider_key()

    is_byok = provider_key is not None
    key_id = str(provider_key.id) if provider_key else None

    input_raw, output_raw = extract_event_io(event_type, properties)
    tools_raw = extract_event_tools(properties)

    input_data = extract_text_from_messages(input_raw)
    output_data = extract_text_from_messages(output_raw)
    tools_data = format_tool_definitions(tools_raw)

    type_config = get_output_type_config(allows_na)
    system_prompt = build_system_prompt(prompt, allows_na)
    response_format = type_config.response_format

    sections = [f"Input: {input_data}"]
    if tools_data:
        sections.append(f"Tools available:\n{tools_data}")
    sections.append(f"Output: {output_data}")
    user_prompt = "\n\n".join(sections)

    config = get_eval_config(provider) if provider_key is None else None

    client = Client(
        provider_key=provider_key,
        config=config,
        capture_analytics=False,
    )

    try:
        response = client.complete(
            CompletionRequest(
                model=model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                provider=provider,
                response_format=response_format,
            )
        )
    except AuthenticationError:
        increment_errors("auth_error", provider=provider)
        if is_byok:
            raise ApplicationError(
                "API key is invalid or has been deleted.",
                {"error_type": "auth_error", "key_id": key_id, "provider": provider},
                non_retryable=True,
            )
        raise
    except ModelPermissionError:
        increment_errors("permission_error", provider=provider)
        if is_byok:
            raise ApplicationError(
                "API key doesn't have access to this model.",
                {"error_type": "permission_error", "key_id": key_id, "provider": provider},
                non_retryable=True,
            )
        raise
    except QuotaExceededError:
        increment_errors("quota_error", provider=provider)
        if is_byok:
            raise ApplicationError(
                "API key has exceeded its quota.",
                {"error_type": "quota_error", "key_id": key_id, "provider": provider},
                non_retryable=True,
            )
        raise
    except RateLimitError:
        increment_errors("rate_limit", provider=provider)
        if is_byok:
            raise ApplicationError(
                "API key is being rate limited.",
                {"error_type": "rate_limit", "key_id": key_id, "provider": provider},
                non_retryable=True,
            )
        raise
    except ModelNotFoundError:
        increment_errors("model_not_found", provider=provider)
        raise ApplicationError(
            f"Model '{model}' not found.",
            non_retryable=True,
        )
    except StructuredOutputParseError as e:
        increment_errors("parse_error", provider=provider)
        raise ApplicationError(
            str(e),
            {"error_type": "parse_error"},
            non_retryable=True,
        ) from e

    except Exception as e:
        logger.exception(
            "Unhandled error from LLM client",
            evaluation_id=evaluation["id"],
            provider=provider,
            model=model,
            error_class=type(e).__name__,
        )
        increment_errors(type(e).__name__, provider=provider)
        raise

    result = response.parsed
    if result is None:
        logger.exception("LLM judge returned empty structured response", evaluation_id=evaluation["id"])
        raise ValueError(f"LLM judge returned empty structured response for evaluation {evaluation['id']}")

    assert isinstance(result, BooleanEvalResult | BooleanWithNAEvalResult)

    usage = response.usage

    if temporalio.activity.in_activity():
        increment_key_type("byok" if is_byok else "posthog")
        increment_provider_model(provider, model)
        if usage:
            increment_tokens("input", usage.input_tokens)
            increment_tokens("output", usage.output_tokens)
            increment_tokens("total", usage.total_tokens)
        bind_contextvars(provider=provider, model=model)

    result_dict: EvaluationActivityResult = {
        "result_type": "boolean",
        "verdict": result.verdict,
        "reasoning": result.reasoning,
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
        "is_byok": is_byok,
        "key_id": key_id,
        "allows_na": allows_na,
        "model": model,
        "provider": provider,
    }

    if allows_na and isinstance(result, BooleanWithNAEvalResult):
        result_dict["applicable"] = result.applicable
    elif isinstance(result, BooleanEvalResult):
        pass
    else:
        raise ValueError(f"Unexpected result type: {type(result)}")

    return result_dict
