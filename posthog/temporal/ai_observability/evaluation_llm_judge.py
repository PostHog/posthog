import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
import temporalio
import posthoganalytics
from pydantic import BaseModel, model_validator
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.evaluation_errors import (
    require_user_error_spec,
    terminal_user_error_result,
    terminal_user_error_result_from_application_error,
)
from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io, extract_event_tools
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.message_utils import extract_text_from_messages, format_tool_definitions
from posthog.temporal.ai_observability.metrics import (
    increment_errors,
    increment_key_type,
    increment_provider_model,
    increment_tokens,
    increment_user_errors,
)
from posthog.temporal.ai_observability.model_resolution import model_spec

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER, Client, CompletionRequest
from products.ai_observability.backend.llm.config import get_eval_config
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    ModelNotFoundError,
    ModelPermissionError,
    QuotaExceededError,
    RateLimitError,
    StructuredOutputParseError,
)

logger = structlog.get_logger(__name__)

DEFAULT_JUDGE_MODEL = DEFAULT_MODEL_BY_PROVIDER["openai"]

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

    input_raw, output_raw = extract_event_io(event_type, properties)
    tools_raw = extract_event_tools(properties)

    input_data = extract_text_from_messages(input_raw)
    output_data = extract_text_from_messages(output_raw)
    tools_data = format_tool_definitions(tools_raw)

    system_prompt = build_system_prompt(prompt, allows_na)

    sections = [f"Input: {input_data}"]
    if tools_data:
        sections.append(f"Tools available:\n{tools_data}")
    sections.append(f"Output: {output_data}")
    user_prompt = "\n\n".join(sections)

    return call_llm_judge(
        evaluation=evaluation,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        allows_na=allows_na,
    )


def call_llm_judge(
    *,
    evaluation: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    allows_na: bool,
) -> EvaluationActivityResult:
    """Resolve the judge model/key for `evaluation` and run a single judge completion.

    Shared by the single-event and trace-level judge activities — everything from provider
    resolution through error mapping and result shaping is identical between them; only how the
    user prompt is assembled differs.
    """
    team_id = evaluation["team_id"]
    try:
        resolved = model_spec(evaluation.get("model_configuration")).resolve(team_id)
    except ApplicationError as e:
        terminal_result = terminal_user_error_result_from_application_error(e, allows_na=allows_na)
        if terminal_result is not None:
            increment_user_errors(terminal_result["skip_reason"], provider=terminal_result.get("provider"))
            return terminal_result
        raise

    provider = resolved.provider
    model = resolved.model
    provider_key = resolved.provider_key
    is_byok = resolved.is_byok
    key_id = str(provider_key.id) if provider_key else None

    type_config = get_output_type_config(allows_na)
    response_format = type_config.response_format

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
        if is_byok:
            increment_user_errors("auth_error", provider=provider)
            return terminal_user_error_result(
                spec=require_user_error_spec("auth_error", is_byok=True),
                message="API key is invalid or has been deleted.",
                allows_na=allows_na,
                provider=provider,
                model=model,
                key_id=key_id,
                is_byok=True,
            )
        increment_errors("auth_error", provider=provider)
        raise
    except ModelPermissionError:
        if is_byok:
            increment_user_errors("permission_error", provider=provider)
            return terminal_user_error_result(
                spec=require_user_error_spec("permission_error", is_byok=True),
                message="API key doesn't have access to this model.",
                allows_na=allows_na,
                provider=provider,
                model=model,
                key_id=key_id,
                is_byok=True,
            )
        increment_errors("permission_error", provider=provider)
        raise
    except QuotaExceededError:
        if is_byok:
            increment_user_errors("quota_error", provider=provider)
            return terminal_user_error_result(
                spec=require_user_error_spec("quota_error", is_byok=True),
                message="API key has exceeded its quota.",
                allows_na=allows_na,
                provider=provider,
                model=model,
                key_id=key_id,
                is_byok=True,
            )
        increment_errors("quota_error", provider=provider)
        raise
    except RateLimitError:
        if is_byok:
            increment_user_errors("rate_limit", provider=provider)
            return terminal_user_error_result(
                spec=require_user_error_spec("rate_limit", is_byok=True),
                message="API key is being rate limited.",
                allows_na=allows_na,
                provider=provider,
                model=model,
                key_id=key_id,
                is_byok=True,
            )
        increment_errors("rate_limit", provider=provider)
        raise
    except ModelNotFoundError:
        if is_byok:
            increment_user_errors("model_not_found", provider=provider)
            return terminal_user_error_result(
                spec=require_user_error_spec("model_not_found", is_byok=True),
                message=f"Model '{model}' not found.",
                allows_na=allows_na,
                provider=provider,
                model=model,
                key_id=key_id,
                is_byok=True,
            )
        increment_errors("model_not_found", provider=provider)
        raise ApplicationError(
            f"Model '{model}' not found.",
            {"error_type": "model_not_found", "provider": provider, "model": model},
            non_retryable=True,
        )
    except StructuredOutputParseError as e:
        increment_errors("parse_error", provider=provider)
        raise ApplicationError(
            str(e),
            {"error_type": "parse_error"},
            non_retryable=True,
        ) from e
    except ContextWindowExceededError as e:
        # Deterministic for this prompt — retrying the identical request only burns attempts.
        increment_errors("context_window_exceeded", provider=provider)
        raise ApplicationError(
            "Trace is too large to fit the judge model's context window.",
            {"error_type": "context_window_exceeded", "provider": provider, "model": model},
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

    parsed_result = response.parsed
    if parsed_result is None:
        logger.exception("LLM judge returned empty structured response", evaluation_id=evaluation["id"])
        raise ValueError(f"LLM judge returned empty structured response for evaluation {evaluation['id']}")

    assert isinstance(parsed_result, BooleanEvalResult | BooleanWithNAEvalResult)

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
        "verdict": parsed_result.verdict,
        "reasoning": parsed_result.reasoning,
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
        "is_byok": is_byok,
        "key_id": key_id,
        "allows_na": allows_na,
        "model": model,
        "provider": provider,
    }

    if allows_na and isinstance(parsed_result, BooleanWithNAEvalResult):
        result_dict["applicable"] = parsed_result.applicable
    elif isinstance(parsed_result, BooleanEvalResult):
        pass
    else:
        raise ValueError(f"Unexpected result type: {type(parsed_result)}")

    return result_dict
