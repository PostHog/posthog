"""Stage 7, after the review: a drafted judge is shown only when the model it will run on agrees with the review.

The review labels every call it read for each card. The card's judge prompt then grades the review's fails and
passes on the team's runtime judge model, one call per request, each call rendered as the review read it. A small
model can miss most of the failures a strong model finds, so a card is kept only when its judge catches most of
the review's fails without flagging many of its passes.
"""

import json
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Literal

import openai
import anthropic
import structlog
from anthropic.types import ToolParam, ToolUseBlock

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client, team_distinct_id

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER

from . import call_review
from .call_review import Rendering, ReviewCard, Verdict, parse_verdict
from .config import AI_PRODUCT
from .prices import MODEL_PRICES

logger = structlog.get_logger(__name__)

CALIBRATION_CALLS = 40
CONCURRENCY = 8
TIMEOUT_SECONDS = 30.0
# Room for a reasoning model's hidden tokens before a one-sentence verdict.
MAX_OUTPUT_TOKENS = 2048
# A judge that misses more than 2 in 5 of the review's fails would hide the failure its card is about.
MIN_CAUGHT_SHARE = 0.6
# One false alarm per two review fails at most, so the real failures stay the bulk of what the judge flags.
FAILS_PER_FALSE_ALARM = 2
# Calibration calls the OpenAI and Anthropic APIs through the Go gateway. A judge on another provider's default is
# not calibrated, so the review does not run for it.
GATEWAY_PROVIDERS: dict[str, Literal["openai", "anthropic"]] = {
    DEFAULT_MODEL_BY_PROVIDER["openai"]: "openai",
    DEFAULT_MODEL_BY_PROVIDER["anthropic"]: "anthropic",
}

_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "fail", "na"]},
    },
    "required": ["reasoning", "verdict"],
    "additionalProperties": False,
}
_VERDICT_TOOL: ToolParam = {
    "name": "record_verdict",
    "description": "Record the verdict on the generation.",
    "input_schema": _VERDICT_SCHEMA,
}


def _system(judge_prompt: str) -> str:
    # Mirrors build_system_prompt for a boolean judge with N/A in posthog/temporal/ai_observability/
    # evaluation_llm_judge.py, so the judge grades here as the accepted evaluation will. Keep the two in step.
    return f"""You are an evaluator. Evaluate the following generation according to this criteria:

{judge_prompt}

First, determine if this evaluation criteria is applicable to the given input/output. If the criteria doesn't apply to this case mark it as not applicable.

Return:
- reasoning: a brief explanation (1 sentence)
- verdict: "pass" if the generation meets the criteria, "fail" if it does not, "na" if the criteria doesn't apply to this input/output"""


@frozen
class JudgeRequest:
    model: str
    system: str
    prompt: str


@frozen
class JudgeCall:
    # None when every attempt failed or the reply held no verdict.
    verdict: Verdict | None
    cost_usd: float


@frozen
class Calibration:
    review_fails: int
    caught: int
    review_passes: int
    false_alarms: int
    # Calls without a verdict: the request failed, the reply held none, or the deadline left no time to start it.
    unjudged: int


def provider(model: str | None) -> Literal["openai", "anthropic"] | None:
    return GATEWAY_PROVIDERS.get(model) if model else None


def build_client(team_id: int, run_id: str, model: str) -> anthropic.Anthropic | openai.OpenAI:
    """A Go gateway client for the model's provider, in privacy mode with the review's product tag and team."""
    kind = provider(model)
    if kind == "anthropic":
        return call_review.build_client(team_id, run_id)
    if kind is None:
        raise ValueError(f"No gateway route to calibrate on {model}")
    client = build_openai_client(
        # Only the Python gateway reads this route, and privacy mode raises instead of falling back to it.
        "django",
        ai_product=AI_PRODUCT,
        trace_id=run_id,
        properties={"team_id": str(team_id)},
        distinct_id=team_distinct_id(team_id),
        privacy_mode=True,
    )
    return client.with_options(max_retries=0)


def calibration_calls(card: ReviewCard) -> list[int]:
    """The review's fails, then its passes, CALIBRATION_CALLS at most. Calls the question does not apply to stay
    out, since a fail rate counts only the calls it applies to."""
    labels = sorted(card.labels.items())
    fails = [number for number, verdict in labels if verdict == "fail"][:CALIBRATION_CALLS]
    passes = [number for number, verdict in labels if verdict == "pass"]
    return fails + passes[: CALIBRATION_CALLS - len(fails)]


def judge_request(card: ReviewCard, rendering: Rendering, number: int, model: str) -> JudgeRequest:
    return JudgeRequest(model=model, system=_system(card.judge_prompt), prompt=rendering.calls[number].text)


def _max_attempt_cost_usd(request: JudgeRequest) -> float:
    """A token covers at least one byte of the request, and output stops at MAX_OUTPUT_TOKENS."""
    price = MODEL_PRICES[request.model]
    request_bytes = len(json.dumps([request.system, request.prompt, _VERDICT_SCHEMA]).encode())
    return request_bytes * price.input_per_token + MAX_OUTPUT_TOKENS * price.output_per_token


def max_cost_usd(requests: Sequence[JudgeRequest]) -> float:
    """What the run reserves before the requests: the most every attempt of every request can bill together."""
    return call_review.ATTEMPTS * sum(_max_attempt_cost_usd(request) for request in requests)


def _attempt(client: anthropic.Anthropic | openai.OpenAI, request: JudgeRequest) -> JudgeCall:
    price = MODEL_PRICES[request.model]
    if isinstance(client, anthropic.Anthropic):
        response = client.messages.create(
            model=request.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=request.system,
            messages=[{"role": "user", "content": request.prompt}],
            tools=[_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": _VERDICT_TOOL["name"]},
            timeout=TIMEOUT_SECONDS,
        )
        answer: Any = next((block.input for block in response.content if isinstance(block, ToolUseBlock)), None)
        usage = response.usage
        cost = usage.input_tokens * price.input_per_token + usage.output_tokens * price.output_per_token
    else:
        completion = client.chat.completions.create(
            model=request.model,
            messages=[{"role": "system", "content": request.system}, {"role": "user", "content": request.prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "verdict", "strict": True, "schema": _VERDICT_SCHEMA},
            },
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            timeout=TIMEOUT_SECONDS,
        )
        try:
            answer = json.loads(completion.choices[0].message.content or "") if completion.choices else None
        except ValueError:
            answer = None
        tokens = completion.usage
        cost = (
            tokens.prompt_tokens * price.input_per_token + tokens.completion_tokens * price.output_per_token
            if tokens
            else _max_attempt_cost_usd(request)
        )
    verdict = parse_verdict(answer.get("verdict")) if isinstance(answer, dict) else None
    return JudgeCall(verdict=verdict, cost_usd=cost)


def _retryable(error: anthropic.APIError | openai.APIError) -> bool:
    if isinstance(
        error,
        anthropic.APIConnectionError
        | anthropic.RateLimitError
        | anthropic.InternalServerError
        | openai.APIConnectionError
        | openai.RateLimitError
        | openai.InternalServerError,
    ):
        return True
    return isinstance(error, anthropic.APIStatusError | openai.APIStatusError) and error.status_code == 408


def judge(client: anthropic.Anthropic | openai.OpenAI, request: JudgeRequest) -> JudgeCall:
    """One forced verdict. An attempt that fails may have billed, so it counts at its most, except a 429, which the
    provider refuses before any work. When every attempt fails, the call has no verdict."""
    unsettled = 0.0
    for attempt in range(call_review.ATTEMPTS):
        try:
            served = _attempt(client, request)
            return replace(served, cost_usd=served.cost_usd + unsettled)
        except (anthropic.APIError, openai.APIError) as error:
            if not isinstance(error, anthropic.RateLimitError | openai.RateLimitError):
                unsettled += _max_attempt_cost_usd(request)
            if attempt == call_review.ATTEMPTS - 1 or not _retryable(error):
                logger.warning(
                    "eval_suggestions_calibration_call_failed", model=request.model, error=type(error).__name__
                )
                break
            time.sleep(call_review.RETRY_BACKOFF_SECONDS * (attempt + 1))
    return JudgeCall(verdict=None, cost_usd=unsettled)


def judge_all(
    client: anthropic.Anthropic | openai.OpenAI, requests: Sequence[JudgeRequest], deadline: float | None
) -> list[JudgeCall | None]:
    """Every request, CONCURRENCY at a time. A request starts only while its slowest run still ends before
    `deadline`, a time.monotonic() value. One that does not start is None and costs nothing."""

    def run(request: JudgeRequest) -> JudgeCall | None:
        if deadline is not None and time.monotonic() + call_review.max_seconds(TIMEOUT_SECONDS) > deadline:
            return None
        return judge(client, request)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        return list(pool.map(run, requests))


def calibrate(card: ReviewCard, numbers: Sequence[int], verdicts: Sequence[Verdict | None]) -> Calibration:
    """The judge's verdicts on the calls `numbers` against the review's labels of them."""
    pairs = [(card.labels[number], verdict) for number, verdict in zip(numbers, verdicts, strict=True)]
    return Calibration(
        review_fails=sum(1 for label, _ in pairs if label == "fail"),
        caught=sum(1 for label, verdict in pairs if label == "fail" and verdict == "fail"),
        review_passes=sum(1 for label, _ in pairs if label == "pass"),
        false_alarms=sum(1 for label, verdict in pairs if label == "pass" and verdict == "fail"),
        unjudged=sum(1 for _, verdict in pairs if verdict is None),
    )


def keeps(calibration: Calibration) -> bool:
    fails = calibration.review_fails
    return (
        fails > 0
        and calibration.caught / fails >= MIN_CAUGHT_SHARE
        and calibration.false_alarms <= max(1, fails // FAILS_PER_FALSE_ALARM)
    )


def measured(card: ReviewCard, calibration: Calibration) -> ReviewCard:
    """The card with the judge's own fail count over the review's applicable calls. When the review passed more
    calls than calibration read, the judge's false alarms among those it read stand for the rest too."""
    fails = sum(1 for verdict in card.labels.values() if verdict == "fail")
    caught = calibration.caught * fails / calibration.review_fails if calibration.review_fails else 0.0
    passes = card.of - fails
    false_alarms = calibration.false_alarms * passes / calibration.review_passes if calibration.review_passes else 0.0
    return replace(card, failed=round(caught + false_alarms))
