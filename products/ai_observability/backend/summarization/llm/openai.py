"""OpenAI provider for LLM summarization, routed through the internal Go ai-gateway
when configured, else the Python LLM gateway."""

from typing import Any, Literal, cast

import structlog
from openai import APITimeoutError, InternalServerError, RateLimitError
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


def build_summarization_messages(text_repr: str, mode: SummarizationMode) -> list[ChatCompletionMessageParam]:
    """Assemble the system and user prompts for one summarization call.

    Shared with the model benchmark command so that a benchmark measures the prompt production
    actually sends, instead of a copy that drifts.
    """
    return [
        {"role": "system", "content": load_summarization_template(f"prompts/system_{mode}.djt", {})},
        {"role": "user", "content": load_summarization_template("prompts/user.djt", {"text_repr": text_repr})},
    ]


# Strict json_schema keeps the model's output parseable by SummarizationResponse without a
# repair step. Shared with the benchmark command for the same reason as the prompts above.
SUMMARIZATION_RESPONSE_FORMAT: Any = cast(
    Any,
    {
        "type": "json_schema",
        "json_schema": {
            "name": "summarization_response",
            "strict": True,
            "schema": SummarizationResponse.model_json_schema(),
        },
    },
)


def summarize_with_openai(
    text_repr: str,
    team_id: int,
    mode: SummarizationMode,
    model: OpenAIModel,
    user_id: str | None = None,
    flex: bool = False,
) -> SummarizationResponse:
    """Generate summary using OpenAI API via LLM gateway with structured outputs."""
    resolved_distinct_id = user_id or team_distinct_id(team_id)
    client = build_openai_client(
        "llma_summarization",
        ai_product="aio_summarization",
        properties={"team_id": str(team_id)},
        distinct_id=resolved_distinct_id,
    )

    messages = build_summarization_messages(text_repr, mode)

    extra: dict[str, Any] = {}
    if _is_gpt5_model(model):
        # gpt-5 models spend hidden reasoning tokens that bill as output. Minimal effort
        # removes them without changing the visible summary volume.
        extra["reasoning_effort"] = "minimal"

    def _create(service_tier: Literal["flex"] | None, timeout: float) -> ChatCompletion:
        tier: dict[str, Any] = {"service_tier": service_tier} if service_tier else {}
        return client.chat.completions.create(
            model=str(model),
            messages=messages,
            user=resolved_distinct_id,
            timeout=timeout,
            response_format=SUMMARIZATION_RESPONSE_FORMAT,
            **extra,
            **tier,
        )

    try:
        # Only gpt-5 family models accept service_tier="flex"; gpt-4.1 rejects the field.
        if flex and _is_gpt5_model(model):
            try:
                response = _create("flex", SUMMARIZATION_FLEX_TIMEOUT)
            except (RateLimitError, APITimeoutError, InternalServerError):
                # Flex runs on spare provider capacity, so the call can be refused (429), stall
                # past the client deadline, or die at the gateway's response ceiling (5xx).
                # Retry once at the standard tier so the batch window still gets its summary.
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
