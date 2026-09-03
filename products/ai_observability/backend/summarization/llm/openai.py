"""OpenAI provider for LLM summarization, routed through the internal Go ai-gateway
when configured, else the Python LLM gateway."""

from typing import Any, Literal

import structlog
from openai import APIConnectionError, APIError, APIStatusError, InternalServerError, Omit, OpenAI, RateLimitError, omit
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from rest_framework import exceptions

from posthog.llm.gateway_client import build_openai_client, team_distinct_id
from posthog.llm.openai_flex import FLEX_CAPABLE_MODELS

from ..constants import SUMMARIZATION_FLEX_TIMEOUT, SUMMARIZATION_TIMEOUT
from ..models import OpenAIModel, SummarizationMode
from ..utils import load_summarization_template
from .schema import SummarizationResponse

logger = structlog.get_logger(__name__)


def _is_gpt5_model(model: OpenAIModel) -> bool:
    return str(model).startswith("gpt-5")


def _is_flex_recoverable(error: APIError) -> bool:
    """Whether a failed flex attempt should retry on the standard tier.

    Recoverable: a capacity refusal (429), a connection reset or client timeout
    (APIConnectionError covers its APITimeoutError subclass), any 5xx (the ai-gateway answers
    504 at its buffered-response ceiling), and 408, which OpenAI's flex docs use for a
    server-side flex timeout and the SDK raises as the bare APIStatusError. Anything else
    (400 bad request, auth errors) is a configuration problem the standard tier shares, so it
    propagates instead of masking itself behind a fallback.
    """
    if isinstance(error, RateLimitError | APIConnectionError | InternalServerError):
        return True
    return isinstance(error, APIStatusError) and error.status_code == 408


# Strict json_schema keeps the model's output parseable by SummarizationResponse without a
# repair step.
SUMMARIZATION_RESPONSE_FORMAT: Any = {
    "type": "json_schema",
    "json_schema": {
        "name": "summarization_response",
        "strict": True,
        "schema": SummarizationResponse.model_json_schema(),
    },
}


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

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": load_summarization_template(f"prompts/system_{mode}.djt", {})},
        {"role": "user", "content": load_summarization_template("prompts/user.djt", {"text_repr": text_repr})},
    ]

    # gpt-5 models spend hidden reasoning tokens that bill as output. Minimal effort removes
    # them without changing the visible summary volume. Family-wide on purpose, unlike the
    # flex allowlist: every gpt-5 reasoning model wants minimal effort for this task, and a
    # new one silently paying reasoning tokens is the costlier default mistake.
    # Both kwargs go through the SDK's typed signature; `omit` leaves the field out of the
    # request entirely, where None would send an explicit null.
    reasoning_effort: Literal["minimal"] | Omit = "minimal" if _is_gpt5_model(model) else omit

    def _create(request_client: OpenAI, service_tier: Literal["flex"] | Omit, timeout: float) -> ChatCompletion:
        return request_client.chat.completions.create(
            model=str(model),
            messages=messages,
            user=resolved_distinct_id,
            timeout=timeout,
            response_format=SUMMARIZATION_RESPONSE_FORMAT,
            reasoning_effort=reasoning_effort,
            service_tier=service_tier,
        )

    try:
        if flex and model in FLEX_CAPABLE_MODELS:
            fell_back = False
            try:
                # max_retries=0: the SDK would otherwise retry the recoverable statuses (408,
                # 429, 5xx) up to twice against the same starved tier, each attempt getting the
                # full timeout, and 3 x 180s stacked with the standard attempts below reaches the
                # summarize activity's 900s start_to_close, cutting the fallback mid-flight.
                # Failing over immediately bounds the worst case at 180s + 3 x 120s = 540s.
                response = _create(client.with_options(max_retries=0), "flex", SUMMARIZATION_FLEX_TIMEOUT)
            except APIError as flex_error:
                # Flex runs on spare provider capacity, so the attempt can fail in several
                # documented ways; _is_flex_recoverable names them. Retry once at the standard
                # tier so the window gets its summary.
                if not _is_flex_recoverable(flex_error):
                    raise
                logger.info(
                    "summarization_flex_fell_back",
                    error_type=type(flex_error).__name__,
                    model=str(model),
                    team_id=team_id,
                )
                fell_back = True
                response = _create(client, omit, SUMMARIZATION_TIMEOUT)
            # The response reports the tier that actually served, so production logs answer the
            # two open rollout questions on day one: does the gateway forward service_tier, and
            # how often does flex refuse.
            logger.info(
                "summarization_served_tier",
                service_tier=response.service_tier,
                fell_back=fell_back,
                model=str(model),
                team_id=team_id,
            )
        else:
            response = _create(client, omit, SUMMARIZATION_TIMEOUT)

        content = response.choices[0].message.content
        if not content:
            raise exceptions.ValidationError("OpenAI returned empty response")
        return SummarizationResponse.model_validate_json(content)
    except exceptions.ValidationError:
        raise
    except Exception as e:
        logger.exception("OpenAI API call failed", error=str(e), team_id=team_id, model=model)
        raise exceptions.APIException("Failed to generate summary")
