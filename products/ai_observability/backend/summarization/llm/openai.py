"""OpenAI provider for LLM summarization, routed through the internal Go ai-gateway
when configured, else the Python LLM gateway."""

from typing import Any, Literal

import structlog
from openai import APIConnectionError, APIError, Omit, OpenAI, omit
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from rest_framework import exceptions

from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import build_openai_client, team_distinct_id
from posthog.llm.openai_flex import FLEX_CAPABLE_MODELS, is_flex_recoverable

from ..constants import SUMMARIZATION_FLEX_TIMEOUT, SUMMARIZATION_TIMEOUT
from ..models import OpenAIModel, SummarizationMode
from ..utils import load_summarization_template
from .schema import SummarizationResponse

logger = structlog.get_logger(__name__)


def _is_gpt5_model(model: OpenAIModel) -> bool:
    return str(model).startswith("gpt-5")


def _provider_status(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _failure_reason(error: Exception) -> str | None:
    """A short reason a user can read and quote to support. None when we have nothing to add."""
    status_code = _provider_status(error)
    if status_code is not None:
        return f"the model provider returned {status_code}"
    if isinstance(error, APIConnectionError):
        return "we could not reach the model provider"
    return None


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
                # documented ways; is_flex_recoverable names them. Retry once at the standard
                # tier so the window gets its summary.
                if not is_flex_recoverable(flex_error):
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
        status_code = _provider_status(e)
        reason = _failure_reason(e)
        logger.exception(
            "OpenAI API call failed",
            error=str(e),
            error_type=type(e).__name__,
            provider_status=status_code,
            team_id=team_id,
            model=model,
            flex=flex,
        )
        # The raised exception is a DRF APIException, which the exceptions-hog handler never
        # reports, so capture it here. The fingerprint splits the causes that used to share one
        # issue: a capacity refusal, a malformed request and a provider outage each get their own.
        capture_exception(
            e,
            additional_properties={
                "$exception_fingerprint": f"aio_summarization.{type(e).__name__}"
                + (f".{status_code}" if status_code is not None else ""),
                "team_id": team_id,
                "model": str(model),
                "provider_status": status_code,
                "flex": flex,
            },
        )
        raise exceptions.APIException(
            f"Failed to generate summary ({reason})" if reason else "Failed to generate summary"
        )
