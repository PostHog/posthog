from typing import Any, Literal, NotRequired, Required, TypedDict


class EvaluationActivityResult(TypedDict, total=False):
    """Result produced by evaluation execution activities.

    `total=False` is used as the default so individual fields opt in via `Required` /
    `NotRequired`, making the contract honest about which keys every path actually sets:

    - `result_type` and `reasoning` are set on every path and are `Required`.
    - `verdict` and `allows_na` are set for boolean outputs only.
    - `applicable` is set only when `allows_na=True`.
    - `skipped` and `skip_reason` are set only on the skip path (e.g. errored source trace).
    - `model`, `provider`, `key_id`, `is_byok`, and the `*_tokens` fields come from the LLM
      judge success path. The skip path omits `model`/`provider` so downstream cost
      attribution doesn't credit phantom calls, and `execute_hog_eval_activity` (whose
      output also flows into `emit_evaluation_event_activity`) emits only `verdict`,
      `reasoning`, `allows_na`, and optionally `applicable`.
    - `sentiment_*` fields are set for sentiment evaluations and deliberately omit
      `verdict` so report and pass/fail metrics do not treat sentiment as N/A.
    """

    result_type: Required[Literal["boolean", "sentiment"]]
    reasoning: Required[str]
    verdict: NotRequired[bool | None]
    allows_na: NotRequired[bool]
    input_tokens: NotRequired[int]
    output_tokens: NotRequired[int]
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
