from typing import Any, Literal, NotRequired, Required, TypedDict

# Workflow id prefix per evaluation type. The Node scheduler builds the live path's ids from
# the same prefixes (nodejs/src/ai-observability/services/temporal.service.ts), so a backfill
# child collides with a live run of the same unit instead of evaluating it twice.
EVALUATION_WORKFLOW_PREFIXES = {
    "hog": "llma-hog-eval",
    "llm_judge": "llma-llm-eval",
    "sentiment": "llma-sentiment-eval",
}

GENERATION_NOT_FOUND = "generation_not_found"


class EvaluationActivityResult(TypedDict, total=False):
    """Result produced by evaluation execution activities.

    `total=False` is used as the default so individual fields opt in via `Required` /
    `NotRequired`, making the contract honest about which keys every path actually sets:

    - `result_type` and `reasoning` are set on every path and are `Required`.
    - `verdict` is set for boolean outputs only; `allows_na` is also set for numeric and categorical outputs.
    - `score` and configured `score_min`/`score_max` are set for applicable numeric outputs.
      Skipped and not-applicable numeric outputs omit these fields and never set `verdict`.
    - `applicable` is set only when `allows_na=True`.
    - `skipped` and `skip_reason` are set only on the skip path (e.g. errored source trace).
    - `model`, `provider`, `key_id`, `is_byok`, and the `*_tokens` fields come from the LLM
      judge success path. The skip path omits `model`/`provider` so downstream cost
      attribution doesn't credit phantom calls, and `execute_hog_eval_activity` (whose
      output also flows into `emit_evaluation_event_activity`) omits model and token fields.
    - `sentiment_*` fields are set for successful sentiment evaluations (the skip path
      omits them) and deliberately omit `verdict` so report and pass/fail metrics do
      not treat sentiment as N/A.
    """

    result_type: Required[Literal["boolean", "sentiment", "numeric", "categorical"]]
    reasoning: Required[str]
    verdict: NotRequired[bool | None]
    probability: NotRequired[float]
    score: NotRequired[float]
    score_min: NotRequired[float]
    score_max: NotRequired[float]
    categories: NotRequired[list[str]]
    allows_na: NotRequired[bool]
    input_tokens: NotRequired[int | None]
    output_tokens: NotRequired[int | None]
    total_tokens: NotRequired[int]
    is_byok: NotRequired[bool]
    key_id: NotRequired[str | None]
    model: NotRequired[str]
    provider: NotRequired[str]
    applicable: NotRequired[bool]
    skipped: NotRequired[bool]
    skip_reason: NotRequired[str]
    terminal_user_error: NotRequired[bool]
    status_reason: NotRequired[str | None]
    provider_key_state: NotRequired[str]
    sentiment_label: NotRequired[str]
    sentiment_score: NotRequired[float]
    sentiment_scores: NotRequired[dict[str, float]]
    sentiment_messages: NotRequired[dict[str, dict[str, Any]]]
    sentiment_message_count: NotRequired[int]


def build_skipped_evaluation_result(
    *,
    output_type: str,
    allows_na: bool,
    reasoning: str,
    skip_reason: str,
    verdict: bool | None = False,
) -> EvaluationActivityResult:
    result: EvaluationActivityResult = {
        "result_type": "categorical"
        if output_type == "categorical"
        else "numeric"
        if output_type == "numeric"
        else "boolean",
        "reasoning": reasoning,
        "allows_na": allows_na,
        "skipped": True,
        "skip_reason": skip_reason,
    }
    if output_type not in ("numeric", "categorical"):
        result["verdict"] = None if allows_na else verdict
    if allows_na:
        result["applicable"] = False
    return result


def build_skipped_sentiment_result(*, reasoning: str, skip_reason: str) -> EvaluationActivityResult:
    return {
        "result_type": "sentiment",
        "reasoning": reasoning,
        "skipped": True,
        "skip_reason": skip_reason,
    }


def build_generation_not_found_result(evaluation: dict[str, Any]) -> EvaluationActivityResult:
    """Skip for a generation that left `ai_events` before its evaluation ran.

    The workflow returns this skip without an emit, because an $ai_evaluation event needs the
    generation that it grades.
    """
    reasoning = "Generation not found; evaluation skipped."
    output_type = evaluation.get("output_type", "boolean")
    if output_type == "sentiment":
        return build_skipped_sentiment_result(reasoning=reasoning, skip_reason=GENERATION_NOT_FOUND)
    return build_skipped_evaluation_result(
        output_type=output_type,
        allows_na=(evaluation.get("output_config") or {}).get("allows_na", False),
        reasoning=reasoning,
        skip_reason=GENERATION_NOT_FOUND,
    )
