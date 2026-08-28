"""OpenAI provider for LLM summarization, routed through the internal Go ai-gateway
when configured, else the Python LLM gateway."""

from typing import Any, cast

import structlog
from openai.types.chat import ChatCompletionMessageParam
from rest_framework import exceptions

from posthog.llm.gateway_client import build_openai_client, team_distinct_id

from ..constants import SUMMARIZATION_TIMEOUT
from ..models import OpenAIModel, SummarizationMode
from ..utils import load_summarization_template
from .schema import SummarizationResponse

logger = structlog.get_logger(__name__)


def summarize_with_openai(
    text_repr: str,
    team_id: int,
    mode: SummarizationMode,
    model: OpenAIModel,
    user_id: str | None = None,
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

    try:
        response = client.chat.completions.create(
            model=str(model),
            messages=messages,
            user=resolved_distinct_id,
            timeout=SUMMARIZATION_TIMEOUT,
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
        )

        content = response.choices[0].message.content
        if not content:
            raise exceptions.ValidationError("OpenAI returned empty response")
        return SummarizationResponse.model_validate_json(content)
    except exceptions.ValidationError:
        raise
    except Exception as e:
        logger.exception("OpenAI API call failed", error=str(e), team_id=team_id, model=model)
        raise exceptions.APIException("Failed to generate summary")
