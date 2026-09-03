"""OpenAI provider for LLM summarization, routed through the internal Go ai-gateway
when configured, else the Python LLM gateway."""

from typing import Any, Literal, cast

import structlog
from openai import APITimeoutError, RateLimitError
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from rest_framework import exceptions

from posthog.llm.gateway_client import build_openai_client, team_distinct_id

from ..constants import SUMMARIZATION_FLEX_TIMEOUT, SUMMARIZATION_TIMEOUT
from ..models import OpenAIModel, SummarizationMode
from ..utils import load_summarization_template
from .schema import SummarizationResponse

logger = structlog.get_logger(__name__)


def _is_gpt5_model(model: OpenAIModel) -> bool:
    return str(model).startswith("gpt-5")


def summarize_with_openai(
    text_repr: str,
    team_id: int,
    mode: SummarizationMode,
    model: OpenAIModel,
    user_id: str | None = None,
    flex: bool = False,
) -> SummarizationResponse:
    """Generate summary using OpenAI API via LLM gateway with structured outputs."""
    system_prompt = load_summarization_template(f"prompts/system_{mode}.djt", {})
    user_prompt = load_summarization_template("prompts/user.djt", {"text_repr": text_repr})

    resolved_distinct_id = user_id or team_distinct_id(team_id)
    client = build_openai_client(
        "llma_summarization",
        ai_product="aio_summarization",
        properties={"team_id": str(team_id)},
        distinct_id=resolved_distinct_id,
    )

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    def _create(service_tier: Literal["flex"] | None, timeout: float) -> ChatCompletion:
        extra: dict[str, Any] = {}
        if _is_gpt5_model(model):
            # gpt-5 models are reasoning models, and reasoning tokens bill as output
            # tokens. Minimal effort keeps output volume at gpt-4.1 levels.
            extra["reasoning_effort"] = "minimal"
        if service_tier is not None:
            extra["service_tier"] = service_tier
        return client.chat.completions.create(
            model=str(model),
            messages=messages,
            user=resolved_distinct_id,
            timeout=timeout,
            response_format=cast(
                Any,
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "summarization_response",
                        "strict": True,
                        "schema": SummarizationResponse.model_json_schema(),
                    },
                },
            ),
            **extra,
        )

    # Only gpt-5 family models accept service_tier="flex"; gpt-4.1 requests would be rejected.
    use_flex = flex and _is_gpt5_model(model)
    try:
        if use_flex:
            try:
                response = _create("flex", SUMMARIZATION_FLEX_TIMEOUT)
            except (RateLimitError, APITimeoutError):
                # Flex runs on spare provider capacity, so OpenAI can refuse (429) or stall
                # the request. Retry once at the standard tier so the window still gets its summary.
                response = _create(None, SUMMARIZATION_TIMEOUT)
        else:
            response = _create(None, SUMMARIZATION_TIMEOUT)

        content = response.choices[0].message.content
        if not content:
            raise exceptions.ValidationError("OpenAI returned empty response")
        return SummarizationResponse.model_validate_json(content)
    except exceptions.ValidationError:
        raise
    except Exception as e:
        logger.exception("OpenAI API call failed", error=str(e), team_id=team_id, model=model)
        raise exceptions.APIException("Failed to generate summary")
