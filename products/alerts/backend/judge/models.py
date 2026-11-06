"""The models the AI series judge can ask, keyed by a stable name.

Each entry knows its provider's gateway client, how that provider takes the chart, and how it
returns the structured verdict. The primary model decides every check. Any other entry can be
asked the same question as a shadow, whose verdict is recorded and never acted on.
"""

from collections.abc import Callable, Mapping
from typing import Any, Literal

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_ai_gateway_anthropic_client, build_ai_gateway_openai_client

from products.alerts.backend.judge.prompt import SYSTEM_PROMPT, JudgePrompt, anthropic_user_content, openai_user_content
from products.alerts.backend.judge.verdict import LLMDetectionVerdict

# Own product key in LLM analytics, so this judge's spend is separable from the
# investigation agent's. Shared by every model, so a shadow call's spend stays with the judge's.
LLM_DETECTOR_AI_PRODUCT = "alert_llm_detector"

# The verdict schema is a handful of fields; this only needs to cover that.
MAX_OUTPUT_TOKENS = 1024


@frozen
class ModelCall:
    """One request to a model, already attributed and labelled for LLM analytics."""

    prompt: JudgePrompt
    team_id: int
    trace_id: str
    # Labels on the gateway's $ai_generation event. The gateway reads them from request headers
    # before the model answers, so they cannot carry anything from the verdict.
    properties: Mapping[str, str]
    extra_headers: Mapping[str, str]
    timeout_seconds: float
    max_retries: int


@frozen
class JudgeModel:
    # Stable across provider renames: it is recorded on checks and in the flag payload.
    name: str
    provider: Literal["anthropic", "openai"]
    model_id: str
    # Raises the provider SDK's own errors, or a ValueError when the gateway is not configured.
    # Returns whatever the SDK parsed, which the caller checks is a verdict.
    ask: Callable[["JudgeModel", ModelCall], Any]


def _ask_anthropic(model: JudgeModel, call: ModelCall) -> Any:
    client = build_ai_gateway_anthropic_client(
        ai_product=LLM_DETECTOR_AI_PRODUCT,
        trace_id=call.trace_id,
        properties=call.properties,
        team_id=call.team_id,
    )
    with client:
        response = client.with_options(max_retries=call.max_retries, timeout=call.timeout_seconds).messages.parse(
            model=model.model_id,
            max_tokens=MAX_OUTPUT_TOKENS,
            # No temperature: Haiku 5.5 rejects non-default sampling params with a 400. Disabled
            # thinking is accepted only at effort "high" or below, so do not raise the effort past it.
            thinking={"type": "disabled"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": anthropic_user_content(call.prompt)}],  # type: ignore[typeddict-item]
            output_format=LLMDetectionVerdict,
            extra_headers=dict(call.extra_headers),
        )
    return response.parsed_output


def _ask_openai(model: JudgeModel, call: ModelCall) -> Any:
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=LLM_DETECTOR_AI_PRODUCT,
        trace_id=call.trace_id,
        # The OpenAI builder takes no team, so the team label the Anthropic builder adds goes in by hand.
        properties={**call.properties, "team_id": str(call.team_id)},
    )
    with client:
        response = client.with_options(
            max_retries=call.max_retries, timeout=call.timeout_seconds
        ).chat.completions.parse(
            model=model.model_id,
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": openai_user_content(call.prompt)},  # type: ignore[misc,list-item]
            ],
            response_format=LLMDetectionVerdict,
            extra_headers=dict(call.extra_headers),
        )
    return response.choices[0].message.parsed


DEFAULT_JUDGE_MODEL = "claude-haiku-5-5"

JUDGE_MODELS: dict[str, JudgeModel] = {
    model.name: model
    for model in (
        JudgeModel(name="claude-haiku-5-5", provider="anthropic", model_id="claude-haiku-5-5", ask=_ask_anthropic),
        JudgeModel(name="gpt-6-luna", provider="openai", model_id="gpt-6-luna", ask=_ask_openai),
    )
}
