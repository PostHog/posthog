import json
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any, Literal

import structlog
import temporalio
import posthoganalytics
from pydantic import BaseModel, BeforeValidator, Field
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.llm.system_one import (
    MAX_SCORE_LEVELS,
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
)
from posthog.temporal.ai_observability.evaluation_errors import (
    require_user_error_spec,
    terminal_user_error_result,
    terminal_user_error_result_from_application_error,
    truncate_error_detail,
)
from posthog.temporal.ai_observability.evaluation_event_io import (
    extract_event_io,
    extract_event_tools,
    hydrate_event_reference,
)
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult, build_skipped_evaluation_result
from posthog.temporal.ai_observability.message_utils import extract_text_from_messages, format_tool_definitions
from posthog.temporal.ai_observability.metrics import (
    increment_errors,
    increment_key_type,
    increment_provider_model,
    increment_tokens,
    increment_user_errors,
)
from posthog.temporal.ai_observability.model_resolution import model_spec
from posthog.temporal.common.errors import NonReportableApplicationError, NonReportableError
from posthog.temporal.common.utils import close_db_connections

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER, Client, CompletionRequest, Usage
from products.ai_observability.backend.llm.decisions import (
    DecisionClient,
    DecisionEndpointBlockedError,
    decision_evaluations_enabled,
    is_decision_model,
)
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContentFilteredError,
    ContextWindowExceededError,
    ModelNotFoundError,
    ModelPermissionError,
    OutputTokenLimitError,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderHostUnresolvedError,
    ProviderRequestRejectedError,
    QuotaExceededError,
    RateLimitError,
    RetryableRateLimitError,
    StructuredOutputParseError,
    UnsupportedModelError,
    provider_error_detail,
)
from products.ai_observability.backend.llm.providers.openrouter import OPENROUTER_DECISIONS_BASE_URL, decision_model_ids
from products.ai_observability.backend.llm.types import CompletionResponse
from products.ai_observability.backend.models.evaluation_configs import (
    CategoricalOutputConfig,
    NumericOutputConfig,
    NumericScoreOutOfBounds,
)
from products.ai_observability.backend.text_repr.formatters import add_line_numbers, reduce_by_uniform_sampling

logger = structlog.get_logger(__name__)

DEFAULT_JUDGE_MODEL = DEFAULT_MODEL_BY_PROVIDER["openai"]

# Same cap as the trace-level judge (JUDGE_TRACE_MAX_CHARS).
JUDGE_EVENT_MAX_CHARS = 150_000

LLM_JUDGE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
)

# The deadline bounds recovery even when contention outlasts a few attempts.
BACKFILL_ACTIVITY_TIMEOUT = timedelta(minutes=30)
BACKFILL_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=0,
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
)


# A retry can fix these client errors, so they stay on the retry policy like a 5xx.
# 499 is a cancellation, which Gemini already maps to the transport lane.
_RETRYABLE_CLIENT_ERROR_STATUSES = frozenset({408, 409, 429, 499})


def _is_last_judge_attempt(maximum_attempts: int | None = None) -> bool:
    if not temporalio.activity.in_activity():
        return False
    info = temporalio.activity.info()
    # boffin: keep the caller's retry policy when the server omits it.
    if maximum_attempts is None:
        maximum_attempts = (info.retry_policy or LLM_JUDGE_RETRY_POLICY).maximum_attempts
    return bool(maximum_attempts) and info.attempt >= maximum_attempts


class TransientJudgeError(NonReportableError):
    """A transient transport failure that reached the judge, wrapped to keep it out of error tracking.

    A connection reset interrupts the judge at whatever line it reached, so each occurrence
    fingerprints differently and error tracking files a new issue for it. The Temporal retry policy
    already covers it. This class is a plain exception, not an `ApplicationError`, so the activity
    failure stays retryable.

    The marker class is what keeps it quiet. The worker interceptor wraps the activity from
    outside its decorators and reports every exception it does not recognise, so opting the
    activity out of automatic capture is not enough on its own. `NonReportableError` is one of the
    types the interceptor re-raises untouched. A worker drain needs no marker, because the
    interceptor skips cancellations already.
    """


class BooleanEvalResult(BaseModel):
    """Structured output for boolean evaluation results"""

    reasoning: str
    verdict: bool


_OUTCOME_ALIASES = {
    "n/a": "not_applicable",
    "na": "not_applicable",
    "notapplicable": "not_applicable",
}


def _normalize_outcome(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    cleaned = value.strip().strip(".").lower().replace("-", "_").replace(" ", "_")
    return _OUTCOME_ALIASES.get(cleaned, cleaned)


class BooleanWithNAEvalResult(BaseModel):
    """Structured output for boolean evaluation results that allow N/A.

    One enum rather than an `applicable` flag beside a nullable `verdict`, because no provider's
    JSON Schema subset expresses "verdict is required when applicable is true", so the two-field
    shape let a model return a combination a validator here then rejected. Anthropic does not
    enforce the enum, which is what `_normalize_outcome` is for.
    """

    reasoning: str
    outcome: Annotated[Literal["pass", "fail", "not_applicable"], BeforeValidator(_normalize_outcome)]

    @property
    def applicable(self) -> bool:
        return self.outcome != "not_applicable"

    @property
    def verdict(self) -> bool | None:
        if self.outcome == "not_applicable":
            return None
        return self.outcome == "pass"


class NumericEvalResult(BaseModel):
    reasoning: str
    score: float = Field(strict=True, allow_inf_nan=False)


class NumericWithNAEvalResult(BaseModel):
    reasoning: str
    score: float | None = Field(strict=True, allow_inf_nan=False)

    @property
    def applicable(self) -> bool:
        return self.score is not None


class CategoricalEvalResult(BaseModel):
    reasoning: str
    categories: list[str]


class CategoricalWithNAEvalResult(BaseModel):
    reasoning: str
    categories: list[str] | None


@frozen
class OutputTypeConfig:
    """Configuration for each evaluation output type"""

    response_format: (
        type[BooleanEvalResult]
        | type[BooleanWithNAEvalResult]
        | type[NumericEvalResult]
        | type[NumericWithNAEvalResult]
        | type[CategoricalEvalResult]
        | type[CategoricalWithNAEvalResult]
    )
    instructions: str


def get_output_type_config(
    allows_na: bool,
    *,
    output_type: str = "boolean",
    output_config: dict[str, Any] | None = None,
) -> OutputTypeConfig:
    """Get the output type configuration based on whether N/A is allowed."""
    if output_type == "categorical":
        config = CategoricalOutputConfig.model_validate(output_config or {})
        options = json.dumps([option.model_dump() for option in config.options])
        count = (
            "exactly one category key" if config.selection_mode == "single" else "zero or more distinct category keys"
        )
        instructions = f"Provide a brief reasoning (1 sentence) and categories containing {count} from these options: {options}. Return keys, not display labels."
        if allows_na:
            instructions += " Return categories=null when the criteria does not apply."
        if config.selection_mode == "multiple":
            instructions += " An empty list means no categories apply."
        return OutputTypeConfig(
            response_format=CategoricalWithNAEvalResult if allows_na else CategoricalEvalResult,
            instructions=instructions,
        )
    if output_type == "numeric":
        numeric_config = NumericOutputConfig.model_validate(output_config or {})
        instructions = "Provide a brief reasoning (1 sentence) and a finite numeric score."
        if numeric_config.min is not None:
            instructions += f" The score must be at least {numeric_config.min}."
        if numeric_config.max is not None:
            instructions += f" The score must be at most {numeric_config.max}."
        if numeric_config.step is not None:
            instructions += f" Suggested score increment: {numeric_config.step}; do not round an otherwise valid score."
        if allows_na:
            instructions += " Return score=null when the criteria does not apply."
        return OutputTypeConfig(
            response_format=NumericWithNAEvalResult if allows_na else NumericEvalResult, instructions=instructions
        )
    if allows_na:
        return OutputTypeConfig(
            response_format=BooleanWithNAEvalResult,
            instructions="""First, determine if this evaluation criteria is applicable to the given input/output. If the criteria doesn't apply to this case mark it as not applicable.

Note: If the criteria above instructs you to return "N/A", "not applicable", or similar, return an outcome of "not_applicable".

Return:
- reasoning: a brief explanation (1 sentence)
- outcome: "pass" if the generation meets the criteria, "fail" if it does not, "not_applicable" if the criteria doesn't apply to this input/output""",
        )
    return OutputTypeConfig(
        response_format=BooleanEvalResult,
        instructions="Provide a brief reasoning (1 sentence) and a boolean verdict (true/false).",
    )


def build_system_prompt(
    prompt: str, allows_na: bool, *, output_type: str = "boolean", output_config: dict[str, Any] | None = None
) -> str:
    """Build the system prompt for the LLM judge."""
    config = get_output_type_config(allows_na, output_type=output_type, output_config=output_config)
    return f"""You are an evaluator. Evaluate the following generation according to this criteria:

{prompt}

{config.instructions}"""


@dataclass(frozen=False)
class ExecuteLLMJudgeInputs:
    evaluation: dict[str, Any]
    event_data: dict[str, Any]
    retry_maximum_attempts: int | None = None

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


def _build_errored_trace_result(allows_na: bool, *, output_type: str = "boolean") -> EvaluationActivityResult:
    """Result returned when the source trace errored — skips the LLM call entirely.

    Omit `model` and `provider` so the emitted event does not attribute a call that never ran.
    """
    reasoning = "Source trace errored before producing output; evaluation skipped."
    result: EvaluationActivityResult = {
        **build_skipped_evaluation_result(
            output_type=output_type,
            allows_na=allows_na,
            reasoning=reasoning,
            skip_reason="trace_errored",
        ),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "is_byok": False,
        "key_id": None,
    }
    return result


def _build_context_window_skip_result(
    allows_na: bool, *, is_byok: bool, key_id: str | None, output_type: str = "boolean"
) -> EvaluationActivityResult:
    """Per-item skip, not a terminal user error that disables the eval."""
    result: EvaluationActivityResult = {
        **build_skipped_evaluation_result(
            output_type=output_type,
            allows_na=allows_na,
            reasoning="Evaluation input exceeded the model's context window; evaluation skipped.",
            skip_reason="context_window_exceeded",
        ),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "is_byok": is_byok,
        "key_id": key_id,
    }
    return result


def _build_output_limit_skip_result(
    allows_na: bool, *, is_byok: bool, key_id: str | None, provider: str, model: str, output_type: str = "boolean"
) -> EvaluationActivityResult:
    """Per-item skip for a judge reply that hit the model's output limit.

    Carries `model` and `provider` for the same reason the unparsable skip does: the model ran
    and the call was billed. The provider reports no usage counts on this path, because the
    failure reaches us as an exception.
    """
    result = build_skipped_evaluation_result(
        output_type=output_type,
        allows_na=allows_na,
        reasoning="Evaluation model hit its output limit before it finished; evaluation skipped.",
        skip_reason="output_limit_exceeded",
    )
    result.update({"is_byok": is_byok, "key_id": key_id, "model": model, "provider": provider})
    return result


def _build_content_filtered_skip_result(
    allows_na: bool, *, is_byok: bool, key_id: str | None, provider: str, model: str, output_type: str = "boolean"
) -> EvaluationActivityResult:
    """Per-item skip for a judge call the provider's content filter refused.

    Backfills treat it as covered, like an over-window prompt, because a re-run sends the same
    content to the same filter.
    """
    result = build_skipped_evaluation_result(
        output_type=output_type,
        allows_na=allows_na,
        reasoning="Evaluation model's content filter refused the input; evaluation skipped.",
        skip_reason="content_filtered",
    )
    result.update({"is_byok": is_byok, "key_id": key_id, "model": model, "provider": provider})
    return result


def _build_unparsable_response_skip_result(
    allows_na: bool,
    *,
    is_byok: bool,
    key_id: str | None,
    provider: str,
    model: str,
    usage: Usage | None,
    output_type: str = "boolean",
) -> EvaluationActivityResult:
    """Per-item skip for a judge response that does not match the requested schema.

    This skip carries `model` and `provider`, unlike the others, because the model did run and
    the call was billed. `usage` is None when the failure reached us as an exception, which drops
    the counts the provider reported.
    """
    result: EvaluationActivityResult = {
        **build_skipped_evaluation_result(
            output_type=output_type,
            allows_na=allows_na,
            reasoning="Evaluation model returned an unreadable response; evaluation skipped.",
            skip_reason="unparsable_response",
        ),
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
        "is_byok": is_byok,
        "key_id": key_id,
        "model": model,
        "provider": provider,
    }
    return result


def _rejected_request_status(error: Exception) -> int | None:
    """The 4xx status of a provider rejection that no retry can fix, or None.

    The OpenAI and Anthropic SDKs put the status on `status_code`. google-genai puts it on `code`.
    """
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        status = getattr(error, "code", None)
    if not isinstance(status, int) or isinstance(status, bool):
        return None
    if 400 <= status < 500 and status not in _RETRYABLE_CLIENT_ERROR_STATUSES:
        return status
    return None


def _build_rejected_request_skip_result(
    allows_na: bool,
    *,
    is_byok: bool,
    key_id: str | None,
    status: int,
    error: Exception,
    output_type: str = "boolean",
) -> EvaluationActivityResult:
    """Per-item skip for a provider rejection that has no specific mapping.

    The provider's message goes into the reasoning, because nothing else tells the user why the
    provider rejected the request.
    """
    reasoning = (
        f"The model provider rejected the evaluation request with status {status}, so this run was skipped. "
        "Check the model and provider settings if this keeps happening."
    )
    detail = truncate_error_detail(provider_error_detail(error) or str(error))
    if detail:
        reasoning = f"{reasoning} Provider message: {detail}"
    result: EvaluationActivityResult = {
        **build_skipped_evaluation_result(
            output_type=output_type,
            allows_na=allows_na,
            reasoning=reasoning,
            skip_reason="request_rejected",
        ),
        "is_byok": is_byok,
        "key_id": key_id,
    }
    return result


@temporalio.activity.defn
@close_db_connections
# capture_exceptions=False: the worker interceptor reports judge failures, and its capture carries
# the team and evaluation ids. A capture inside the activity wins the SDK's dedupe and loses them.
@posthoganalytics.scoped(capture_exceptions=False)
def execute_llm_judge_activity(inputs: ExecuteLLMJudgeInputs) -> EvaluationActivityResult:
    """Execute LLM judge to evaluate the target event.

    Fetches API key configuration internally to avoid passing sensitive data between activities.
    """
    return _execute_llm_judge_activity(inputs)


def _execute_llm_judge_activity(inputs: ExecuteLLMJudgeInputs) -> EvaluationActivityResult:
    evaluation = inputs.evaluation
    event_data = hydrate_event_reference(inputs.event_data)

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
    if output_type not in ("boolean", "numeric", "categorical"):
        raise ApplicationError(
            f"Unsupported output type: {output_type}. Supported types: 'boolean', 'numeric', 'categorical'.",
            non_retryable=True,
        )

    output_config = evaluation.get("output_config", {})
    allows_na = output_config.get("allows_na", False)

    event_type = event_data["event"]
    properties = event_data["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    if _is_errored_trace(properties):
        return _build_errored_trace_result(allows_na, output_type=output_type)

    io = extract_event_io(event_type, properties)
    tools_raw = extract_event_tools(properties)

    input_data = extract_text_from_messages(io.input_raw)
    output_data = extract_text_from_messages(io.output_raw)
    tools_data = format_tool_definitions(tools_raw)

    system_prompt = build_system_prompt(prompt, allows_na, output_type=output_type, output_config=output_config)

    sections = [f"Input: {input_data}"]
    if tools_data:
        sections.append(f"Tools available:\n{tools_data}")
    sections.append(f"Output: {output_data}")
    user_prompt = "\n\n".join(sections)
    if len(user_prompt) > JUDGE_EVENT_MAX_CHARS:
        # Line-number first so the sampler's "gaps indicate omitted content" header is truthful,
        # then hard-truncate to guarantee the cap for low-newline payloads the sampler leaves whole.
        user_prompt = add_line_numbers(user_prompt)
        user_prompt, _ = reduce_by_uniform_sampling(user_prompt, JUDGE_EVENT_MAX_CHARS)
        user_prompt = user_prompt[:JUDGE_EVENT_MAX_CHARS]

    return call_llm_judge(
        evaluation=evaluation,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        allows_na=allows_na,
        retry_maximum_attempts=inputs.retry_maximum_attempts,
    )


def _decision_numeric_score(minimum: float, maximum: float, index: float) -> float:
    last_index = MAX_SCORE_LEVELS - 1
    if index == 0:
        return minimum
    if index == last_index:
        return maximum
    score = (minimum * (last_index - index) + maximum * index) / last_index
    if math.isfinite(score):
        return score
    # Scale first when multiplying large finite bounds would overflow.
    weight = index / last_index
    return minimum * (1 - weight) + maximum * weight


def call_llm_judge(
    *,
    evaluation: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    allows_na: bool,
    retry_maximum_attempts: int | None = None,
) -> EvaluationActivityResult:
    """Resolve the judge model/key for `evaluation` and run a single judge completion.

    Shared by the single-event and trace-level judge activities — everything from provider
    resolution through error mapping and result shaping is identical between them; only how the
    user prompt is assembled differs.
    """
    team_id = evaluation["team_id"]
    output_type = evaluation.get("output_type", "boolean")
    output_config = evaluation.get("output_config") or {}
    try:
        resolved = model_spec(evaluation.get("model_configuration")).resolve(team_id)
    except ApplicationError as e:
        terminal_result = terminal_user_error_result_from_application_error(
            e, allows_na=allows_na, output_type=output_type
        )
        if terminal_result is not None:
            increment_user_errors(terminal_result["skip_reason"], provider=terminal_result.get("provider"))
            return terminal_result
        raise

    provider = resolved.provider
    model = resolved.model
    provider_key = resolved.provider_key
    is_byok = resolved.is_byok
    key_id = str(provider_key.id) if provider_key else None

    type_config = get_output_type_config(allows_na, output_type=output_type, output_config=output_config)
    response_format = type_config.response_format

    config = None

    client = Client(
        provider_key=provider_key,
        config=config,
        capture_analytics=False,
    )

    probability: float | None = None
    decision_result = None
    try:
        openrouter_enabled = provider == "openrouter" and decision_evaluations_enabled(
            team_id, base_url=OPENROUTER_DECISIONS_BASE_URL
        )
        uses_decisions = is_decision_model(provider, model, openrouter_enabled=openrouter_enabled)
        if provider == "openrouter" and not openrouter_enabled:
            uses_decisions = model in (decision_model_ids(refresh=False) or ())
        if uses_decisions:
            if output_type not in ("boolean", "categorical", "numeric"):
                return build_skipped_evaluation_result(
                    output_type=output_type,
                    allows_na=allows_na,
                    reasoning="Decision models support boolean, categorical, and numeric evaluations.",
                    skip_reason="unsupported_output_type",
                )
            base_url = (
                OPENROUTER_DECISIONS_BASE_URL
                if provider == "openrouter"
                else provider_key.encrypted_config.get("base_url", "")
                if provider_key
                else ""
            )
            if (provider == "openrouter" and not openrouter_enabled) or (
                provider == "system_one" and not decision_evaluations_enabled(team_id, base_url=base_url)
            ):
                return build_skipped_evaluation_result(
                    output_type=output_type,
                    allows_na=allows_na,
                    reasoning="Decision model evaluations are not available for this project.",
                    skip_reason="system_one_unavailable",
                )
            prompt = evaluation["evaluation_config"]["prompt"]
            categorical_config = (
                CategoricalOutputConfig.model_validate(output_config) if output_type == "categorical" else None
            )
            numeric_levels: list[float] | None = None
            questions: dict[str, Question]
            if output_type == "numeric":
                numeric_config = NumericOutputConfig.model_validate(output_config)
                if numeric_config.min is None or numeric_config.max is None or numeric_config.min >= numeric_config.max:
                    return build_skipped_evaluation_result(
                        output_type=output_type,
                        allows_na=allows_na,
                        reasoning="Numeric evaluations with decision models require a minimum score below the maximum score.",
                        skip_reason="request_rejected",
                    )
                numeric_levels = [
                    _decision_numeric_score(numeric_config.min, numeric_config.max, index)
                    for index in range(MAX_SCORE_LEVELS)
                ]
                if numeric_config.step is not None:
                    prompt += (
                        f"\nSuggested score increment: {numeric_config.step}; do not round an otherwise valid score."
                    )
                questions = {
                    "score": ScoreQuestion(
                        instructions=prompt,
                        criteria=[
                            f"The score according to the evaluation criteria is {value!r}." for value in numeric_levels
                        ],
                    )
                }
            elif categorical_config is None:
                questions = {"verdict": NoulQuestion(instructions=prompt)}
            elif categorical_config.selection_mode == "single":
                questions = {
                    "category": ChoiceQuestion(
                        instructions=prompt,
                        criteria={option.key: option.label for option in categorical_config.options},
                    )
                }
            else:
                questions = {
                    f"category_{index}": NoulQuestion(
                        instructions=prompt,
                        criteria_true=f"Matches category: {option.label}",
                        criteria_false=f"Does not match category: {option.label}",
                    )
                    for index, option in enumerate(categorical_config.options)
                }
            if allows_na:
                questions["applicable"] = NoulQuestion(
                    instructions=(
                        "Do these evaluation criteria apply to this input? Answer true when the criteria can be "
                        "evaluated, even if they are not met. Answer false only when they are not relevant.\n\n"
                        + prompt
                    )
                )
            decision_result = DecisionClient.evaluate(
                api_key=provider_key.encrypted_config.get("api_key", "") if provider_key else "",
                base_url=base_url,
                path="decisions" if provider == "openrouter" else "systemone",
                model=model,
                state=user_prompt,
                questions=questions,
            )
            applicable = True
            if allows_na:
                applicability_answer = decision_result.answers["applicable"]
                if not isinstance(applicability_answer, NoulAnswer):
                    raise StructuredOutputParseError("The endpoint returned an invalid applicability answer.")
                applicable = applicability_answer.probability >= 0.5
            parsed: (
                BooleanEvalResult
                | BooleanWithNAEvalResult
                | CategoricalEvalResult
                | CategoricalWithNAEvalResult
                | NumericEvalResult
                | NumericWithNAEvalResult
            )
            if numeric_levels is not None:
                score_answer = decision_result.answers["score"]
                if not isinstance(score_answer, ScoreAnswer):
                    raise StructuredOutputParseError("The endpoint returned an invalid score answer.")
                score = _decision_numeric_score(numeric_levels[0], numeric_levels[-1], score_answer.score)
                parsed = (
                    NumericWithNAEvalResult(reasoning="", score=score if applicable else None)
                    if allows_na
                    else NumericEvalResult(reasoning="", score=score)
                )
            elif categorical_config is not None:
                categories: list[str] = []
                if categorical_config.selection_mode == "single":
                    category_answer = decision_result.answers["category"]
                    if not isinstance(category_answer, ChoiceAnswer):
                        raise StructuredOutputParseError("The endpoint returned an invalid category answer.")
                    categories = [category_answer.choice]
                else:
                    for index, option in enumerate(categorical_config.options):
                        category_match = decision_result.answers[f"category_{index}"]
                        if not isinstance(category_match, NoulAnswer):
                            raise StructuredOutputParseError("The endpoint returned an invalid category answer.")
                        if category_match.probability >= 0.5:
                            categories.append(option.key)
                parsed = (
                    CategoricalWithNAEvalResult(reasoning="", categories=categories if applicable else None)
                    if allows_na
                    else CategoricalEvalResult(reasoning="", categories=categories)
                )
            else:
                verdict_answer = decision_result.answers["verdict"]
                if not isinstance(verdict_answer, NoulAnswer):
                    raise StructuredOutputParseError("The endpoint returned an invalid verdict answer.")
                probability = verdict_answer.probability
                parsed = (
                    BooleanWithNAEvalResult(
                        reasoning="",
                        outcome="not_applicable" if not applicable else "pass" if probability >= 0.5 else "fail",
                    )
                    if allows_na
                    else BooleanEvalResult(reasoning="", verdict=probability >= 0.5)
                )
            response = CompletionResponse(
                content="",
                model=model,
                parsed=parsed,
                usage=Usage(
                    input_tokens=(decision_result.input_tokens or 0),
                    output_tokens=(decision_result.output_tokens or 0),
                    total_tokens=(decision_result.input_tokens or 0) + (decision_result.output_tokens or 0),
                ),
            )
        else:
            response = client.complete(
                CompletionRequest(
                    model=model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    provider=provider,
                    response_format=response_format,
                )
            )
    except (DecisionEndpointBlockedError, ProviderConfigurationError) as e:
        increment_user_errors("endpoint_blocked", provider=provider)
        return terminal_user_error_result(
            spec=require_user_error_spec("endpoint_blocked", is_byok=is_byok),
            message=str(e),
            allows_na=allows_na,
            output_type=output_type,
            key_id=key_id,
            is_byok=is_byok,
        )
    except ProviderRequestRejectedError as e:
        increment_user_errors("request_rejected", provider=provider)
        return build_skipped_evaluation_result(
            output_type=output_type,
            allows_na=allows_na,
            reasoning=str(e),
            skip_reason="request_rejected",
        )
    except RetryableRateLimitError as e:
        increment_errors("rate_limit", provider=provider)
        # A retry usually gets through, so only an outage that outlasts every attempt reaches error tracking.
        error_class = (
            ApplicationError if _is_last_judge_attempt(retry_maximum_attempts) else NonReportableApplicationError
        )
        raise error_class(
            str(e),
            {"error_type": "provider_unavailable", "provider": provider},
            next_retry_delay=timedelta(seconds=e.retry_after) if e.retry_after is not None else None,
        ) from e
    except AuthenticationError:
        if is_byok:
            increment_user_errors("auth_error", provider=provider)
            return terminal_user_error_result(
                spec=require_user_error_spec("auth_error", is_byok=True),
                message="API key is invalid or has been deleted.",
                allows_na=allows_na,
                output_type=output_type,
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
                output_type=output_type,
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
                output_type=output_type,
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
                output_type=output_type,
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
                output_type=output_type,
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
    except UnsupportedModelError:
        # A failed chat call can populate a cold catalogue; a disabled flag must not disable the evaluation.
        if provider == "openrouter" and not openrouter_enabled and model in (decision_model_ids(refresh=False) or ()):
            return build_skipped_evaluation_result(
                output_type=output_type,
                allows_na=allows_na,
                reasoning="Decision model evaluations are not available for this project.",
                skip_reason="system_one_unavailable",
            )
        increment_user_errors("model_not_supported", provider=provider)
        return terminal_user_error_result(
            spec=require_user_error_spec("model_not_supported", is_byok=is_byok),
            message=f"Model '{model}' does not support chat completions. Choose a chat model.",
            allows_na=allows_na,
            output_type=output_type,
            provider=provider,
            model=model,
            key_id=key_id,
            is_byok=is_byok,
        )
    except StructuredOutputParseError as e:
        # Skip rather than raise: non-conforming model output is not a PostHog defect, and raising
        # files a new error tracking issue on each deploy, because the fingerprint follows the stack.
        increment_errors("parse_error", provider=provider)
        logger.warning(
            "LLM judge returned unparsable structured output",
            evaluation_id=evaluation["id"],
            provider=provider,
            model=model,
            error=str(e),
        )
        return _build_unparsable_response_skip_result(
            allows_na,
            is_byok=is_byok,
            key_id=key_id,
            provider=provider,
            model=model,
            usage=None,
            output_type=output_type,
        )

    except ContextWindowExceededError:
        # Skip rather than raise: retrying can't fix an over-window prompt and just spams error tracking.
        increment_errors("context_window_exceeded", provider=provider)
        return _build_context_window_skip_result(allows_na, is_byok=is_byok, key_id=key_id, output_type=output_type)

    except OutputTokenLimitError as e:
        # Avoid automatic retries of a billed generation; a later backfill can retry it.
        # Providers word this failure differently, so raising creates separate error tracking issues.
        increment_errors("output_limit_exceeded", provider=provider)
        logger.warning(
            "LLM judge response hit the model output limit",
            evaluation_id=evaluation["id"],
            provider=provider,
            model=model,
            error=str(e),
        )
        return _build_output_limit_skip_result(
            allows_na, is_byok=is_byok, key_id=key_id, provider=provider, model=model, output_type=output_type
        )

    except ContentFilteredError as e:
        # Skip rather than raise: the refusal comes from customer content, so a retry rarely
        # changes it, and raising files a new error tracking issue per call site.
        increment_errors("content_filtered", provider=provider)
        logger.warning(
            "LLM judge request was refused by the provider content filter",
            evaluation_id=evaluation["id"],
            provider=provider,
            model=model,
            error=str(e),
        )
        return _build_content_filtered_skip_result(
            allows_na, is_byok=is_byok, key_id=key_id, provider=provider, model=model, output_type=output_type
        )

    except ProviderHostUnresolvedError as e:
        if not _is_last_judge_attempt(retry_maximum_attempts):
            increment_errors("connection_error", provider=provider)
            raise TransientJudgeError(str(e)) from e
        # The host did not resolve on any attempt, so the base URL is probably wrong. A failed
        # workflow shows the user nothing, so skip the run with the reason instead. A skip leaves
        # the evaluation and its key enabled, because a DNS outage that ends needs no user action.
        increment_user_errors("host_unresolved", provider=provider)
        return build_skipped_evaluation_result(
            output_type=output_type,
            allows_na=allows_na,
            reasoning=str(e),
            skip_reason="host_unresolved",
        )

    except ProviderConnectionError as e:
        # Transient transport failure (connection reset, read timeout). Retrying usually succeeds,
        # so track it as a metric and re-raise for the retry policy. `TransientJudgeError` keeps it
        # out of error tracking, where a per-occurrence fingerprint files a new issue every time.
        increment_errors("connection_error", provider=provider)
        raise TransientJudgeError(str(e)) from e

    except temporalio.exceptions.CancelledError:
        # A worker drain or a workflow cancel is not a judge failure, so track it as a metric and
        # re-raise for the retry policy. The worker interceptor skips cancellations, so it stays
        # out of error tracking.
        increment_errors("cancelled", provider=provider)
        raise

    except Exception as e:
        rejected_status = _rejected_request_status(e)
        # On a PostHog key a rejection is our bug, so it falls through to error tracking below.
        if rejected_status is not None and is_byok:
            # A single bad input and a bad configuration look the same here, so skip this run and
            # leave the evaluation and its key alone.
            increment_user_errors("request_rejected", provider=provider)
            logger.warning(
                "LLM provider rejected the judge request",
                evaluation_id=evaluation["id"],
                provider=provider,
                model=model,
                status=rejected_status,
                error_class=type(e).__name__,
            )
            return _build_rejected_request_skip_result(
                allows_na,
                is_byok=is_byok,
                key_id=key_id,
                status=rejected_status,
                error=e,
                output_type=output_type,
            )
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
        increment_errors("empty_structured_response", provider=provider)
        logger.warning(
            "LLM judge returned empty structured response",
            evaluation_id=evaluation["id"],
            provider=provider,
            model=model,
        )
        return _build_unparsable_response_skip_result(
            allows_na,
            is_byok=is_byok,
            key_id=key_id,
            provider=provider,
            model=model,
            usage=response.usage,
            output_type=output_type,
        )

    assert isinstance(
        parsed_result,
        BooleanEvalResult
        | BooleanWithNAEvalResult
        | NumericEvalResult
        | NumericWithNAEvalResult
        | CategoricalEvalResult
        | CategoricalWithNAEvalResult,
    )

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
    if decision_result is not None:
        result_dict["input_tokens"] = decision_result.input_tokens
        result_dict["output_tokens"] = decision_result.output_tokens

    if isinstance(parsed_result, CategoricalEvalResult | CategoricalWithNAEvalResult):
        result_dict["result_type"] = "categorical"
        if parsed_result.categories is not None:
            try:
                result_dict["categories"] = CategoricalOutputConfig.model_validate(output_config).validate_result(
                    parsed_result.categories
                )
            except ValueError as error:
                increment_errors("parse_error", provider=provider)
                result_dict.update(
                    build_skipped_evaluation_result(
                        output_type="categorical",
                        allows_na=allows_na,
                        reasoning=f"The judge returned invalid categories: {error}. This run was skipped.",
                        skip_reason="parse_error",
                    )
                )
                return result_dict
        if allows_na:
            result_dict["applicable"] = parsed_result.categories is not None
        return result_dict

    if isinstance(parsed_result, NumericEvalResult | NumericWithNAEvalResult):
        result_dict["result_type"] = "numeric"
        if parsed_result.score is not None:
            numeric_config = NumericOutputConfig.model_validate(output_config)
            try:
                result_dict["score"] = numeric_config.validate_score(parsed_result.score)
            except NumericScoreOutOfBounds as error:
                increment_user_errors("score_out_of_bounds", provider=provider)
                result_dict.update(
                    build_skipped_evaluation_result(
                        output_type="numeric",
                        allows_na=allows_na,
                        reasoning=f"{parsed_result.reasoning}\n\nThe judge returned a score outside the configured bounds: {error}. This run was skipped.",
                        skip_reason="score_out_of_bounds",
                    )
                )
                return result_dict
            if numeric_config.min is not None:
                result_dict["score_min"] = numeric_config.min
            if numeric_config.max is not None:
                result_dict["score_max"] = numeric_config.max
        if isinstance(parsed_result, NumericWithNAEvalResult):
            result_dict["applicable"] = parsed_result.applicable
        return result_dict

    result_dict["verdict"] = parsed_result.verdict
    if allows_na and isinstance(parsed_result, BooleanWithNAEvalResult):
        result_dict["applicable"] = parsed_result.applicable
    elif isinstance(parsed_result, BooleanEvalResult):
        pass
    else:
        raise ValueError(f"Unexpected result type: {type(parsed_result)}")

    if probability is not None and result_dict["verdict"] is not None:
        result_dict["probability"] = probability
    return result_dict
