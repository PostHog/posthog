"""Stage 7: one paid model call drafts a check for a failure the catalog does not cover.

Off unless the flag payload turns it on, and capped per coordinator run. A draft is a candidate like any
other: a Hog draft is compiled and measured, a judge draft keeps the evidence of the gap it was written for.
"""

import json
import time
from typing import Any, Literal

import structlog
from openai import APIError, Omit, OpenAI, RateLimitError, omit
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict, ValidationError

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import Product, build_openai_client, team_distinct_id
from posthog.llm.openai_flex import FLEX_CAPABLE_MODELS, is_flex_recoverable

from .profile import StructuredGap, TeamProfile
from .ranking import MODEL_PRICES
from .screening import AI_PRODUCT

logger = structlog.get_logger(__name__)

DRAFT_MODEL = "gpt-5-mini"
# List prices of DRAFT_MODEL, for the per-run budget.
INPUT_PRICE_PER_TOKEN = MODEL_PRICES[DRAFT_MODEL].input_per_token
OUTPUT_PRICE_PER_TOKEN = MODEL_PRICES[DRAFT_MODEL].output_per_token
# Reasoning tokens count against this too, so it bounds what one call can bill for output.
MAX_OUTPUT_TOKENS = 2000
FLEX_TIMEOUT_SECONDS = 180.0
STANDARD_TIMEOUT_SECONDS = 120.0
# Retries on the standard tier, which is the last resort. The budget reserves one call for each.
STANDARD_MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 2.0
# The Python gateway route serves only when the Go gateway is not configured. It is frozen, so the draft
# borrows the AI observability evaluation route rather than adding one.
GATEWAY_ROUTE: Product = "llma_eval_summary"

_SYSTEM_PROMPT = """You write evaluations for an AI observability product. An evaluation is either an LLM judge prompt or a Hog program.

A judge prompt tells a grader model what to check in one trace and when to return true (pass) or false (fail). Write 3 to 6 short rules, each starting with "Return true" or "Return false".

A Hog program reads the global `evaluation_events`, a list of events with `event`, `properties`, `input_text` and `output_text`, and returns true (pass), false (fail) or null (does not apply). Hog uses `let x := value`, `for (let i, item in list) { }`, `if (...) { } else { }`, and functions such as `length`, `lower`, `position`, `match`, `jsonParse` and `print`.

Prefer a Hog program when the failure is visible in fields of the output. Prefer a judge when it needs reading comprehension."""


class _DraftResponse(BaseModel):
    # Strict structured outputs require every object to forbid extra keys.
    model_config = ConfigDict(extra="forbid")

    evaluation_type: Literal["hog", "llm_judge"]
    name: str
    description: str
    body: str


_RESPONSE_FORMAT: Any = {
    "type": "json_schema",
    "json_schema": {"name": "eval_draft", "strict": True, "schema": _DraftResponse.model_json_schema()},
}


@frozen
class Draft:
    evaluation_type: Literal["hog", "llm_judge"]
    name: str
    description: str
    body: str


@frozen
class DraftCall:
    # None when the response held no usable draft. The call bills either way.
    draft: Draft | None
    cost_usd: float


def gap_brief(gap: StructuredGap, profile: TeamProfile) -> str:
    """What the model learns about the failure: aggregates only, never trace content."""
    return json.dumps(
        {
            "finding": "One segment gives a structured output field these values far more often than its siblings.",
            "field": gap.field,
            "values": list(gap.values),
            "segment": {"property": gap.segment_key, "value": gap.segment_value},
            "segment_rate": round(gap.segment_rate, 3),
            "sibling_rate": round(gap.other_rate, 3),
            "tools": sorted(profile.tool_counts)[:20],
            "models": list(profile.models),
        }
    )


def _messages(brief: str) -> list[ChatCompletionMessageParam]:
    return [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": brief}]


def max_draft_seconds() -> float:
    """The longest one draft can take: the flex attempt, then every standard attempt and the waits between them."""
    flex = FLEX_TIMEOUT_SECONDS if DRAFT_MODEL in FLEX_CAPABLE_MODELS else 0.0
    standard = (1 + STANDARD_MAX_RETRIES) * STANDARD_TIMEOUT_SECONDS
    backoff = sum(RETRY_BACKOFF_SECONDS * (attempt + 1) for attempt in range(1 + STANDARD_MAX_RETRIES))
    return flex + standard + backoff


def max_cost_usd(brief: str) -> float:
    """The most one draft can bill, which the run reserves from its budget before calling.

    A token covers at least one byte of the request and output stops at MAX_OUTPUT_TOKENS. Every HTTP
    call can bill: the flex attempt, then the standard tier and each of its retries.
    """
    return (2 + STANDARD_MAX_RETRIES) * _max_call_cost_usd(brief)


def _max_call_cost_usd(brief: str) -> float:
    request_bytes = len(json.dumps([_messages(brief), _RESPONSE_FORMAT]).encode())
    return request_bytes * INPUT_PRICE_PER_TOKEN + MAX_OUTPUT_TOKENS * OUTPUT_PRICE_PER_TOKEN


def _complete(
    client: OpenAI, brief: str, service_tier: Literal["flex"] | Omit, timeout: float, user: str
) -> ChatCompletion:
    return client.chat.completions.create(
        model=DRAFT_MODEL,
        messages=_messages(brief),
        user=user,
        timeout=timeout,
        response_format=_RESPONSE_FORMAT,
        reasoning_effort="minimal",
        max_completion_tokens=MAX_OUTPUT_TOKENS,
        service_tier=service_tier,
    )


def _parse(content: str | None) -> Draft | None:
    if not content:
        return None
    try:
        # A response cut off at MAX_OUTPUT_TOKENS ends mid-JSON.
        parsed = _DraftResponse.model_validate_json(content)
    except ValidationError:
        return None
    return Draft(
        evaluation_type=parsed.evaluation_type,
        name=parsed.name[:80],
        description=parsed.description[:200],
        body=parsed.body,
    )


def draft_check(team_id: int, brief: str, *, privacy_mode: bool) -> DraftCall:
    """`privacy_mode` keeps the brief and the draft out of the gateway's analytics."""
    distinct_id = team_distinct_id(team_id)
    client = build_openai_client(
        GATEWAY_ROUTE,
        ai_product=AI_PRODUCT,
        properties={"team_id": str(team_id)},
        distinct_id=distinct_id,
        privacy_mode=privacy_mode,
    )
    # Retries run here rather than in the SDK, so every failed attempt that may have billed is counted. Only a
    # capacity refusal (429) is known not to bill; any other failure counts at the most one call can cost.
    client = client.with_options(max_retries=0)
    tiers: list[tuple[Literal["flex"] | Omit, float]] = (
        [("flex", FLEX_TIMEOUT_SECONDS)] if DRAFT_MODEL in FLEX_CAPABLE_MODELS else []
    )
    tiers += [(omit, STANDARD_TIMEOUT_SECONDS)] * (1 + STANDARD_MAX_RETRIES)
    unsettled = 0.0
    for attempt, (service_tier, timeout) in enumerate(tiers):
        try:
            response = _complete(client, brief, service_tier, timeout, distinct_id)
            break
        except APIError as error:
            if not is_flex_recoverable(error) or attempt == len(tiers) - 1:
                raise
            if not isinstance(error, RateLimitError):
                unsettled += _max_call_cost_usd(brief)
            if service_tier is omit:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    logger.info("eval_suggestions_draft_served", team_id=team_id, service_tier=response.service_tier)
    usage = response.usage
    cost = (
        (usage.prompt_tokens * INPUT_PRICE_PER_TOKEN + usage.completion_tokens * OUTPUT_PRICE_PER_TOKEN)
        if usage
        else 0.0
    )
    return DraftCall(draft=_parse(response.choices[0].message.content), cost_usd=cost + unsettled)
