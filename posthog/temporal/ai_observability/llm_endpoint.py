"""ChatOpenAI client for the labeling/report agents, routed through the internal
Go ai-gateway when AI_GATEWAY_URL + AI_GATEWAY_API_KEY are set, else direct to OpenAI.

The raw-SDK builders for summarization live in ``posthog.llm.gateway_client`` (importing
from this package would pull in the temporal workflow graph and cycle); this module shares
its ``resolve_ai_gateway_config`` validator and ``ai_gateway_headers`` helper.
"""

import os
from collections.abc import Mapping
from typing import Any, Literal

from django.conf import settings

import httpx
import structlog
import posthoganalytics
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.callbacks.manager import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI
from openai import APIError
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from temporalio.exceptions import ApplicationError

from posthog.cloud_utils import is_cloud
from posthog.llm.gateway_client import ai_gateway_headers, resolve_ai_gateway_config
from posthog.llm.openai_flex import is_flex_recoverable

logger = structlog.get_logger(__name__)

# On a non-cloud, non-DEBUG deployment there is no AI gateway, so this guard fails identically
# every run. The interceptor in posthog/temporal/common/posthog_client.py keeps this error type
# out of error tracking. Raised non-retryably so a stray execution stops on the first attempt.
AI_FEATURES_CLOUD_ONLY_ERROR_TYPE = "AIFeaturesCloudOnly"


class FlexFirstChatOpenAI(ChatOpenAI):
    """ChatOpenAI that retries a failed flex call once on the standard tier, per call.

    The openai SDK's retry loop re-sends the byte-identical request, so it can only
    re-roll a flex capacity refusal. This override retries just the failing chat
    completion with service_tier="default", so an agent loop keeps its completed
    turns instead of rerunning from scratch. Build flex clients with max_retries=0:
    the tier switch is the retry.
    """

    flex_fallback_timeout: float | None = None

    def _flex_fallback_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        fallback = {**kwargs, "service_tier": "default"}
        if self.flex_fallback_timeout is not None:
            # The openai SDK's create() takes timeout as a per-request option, so the
            # standard call gets a standard-sized budget instead of the tight flex one.
            fallback["timeout"] = self.flex_fallback_timeout
        return fallback

    def _log_flex_fallback(self, error: APIError) -> None:
        logger.warning(
            "labeling_flex_call_fell_back",
            error=str(error),
            error_type=type(error).__name__,
            model=self.model_name,
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except APIError as error:
            if self.service_tier != "flex" or not is_flex_recoverable(error):
                raise
            self._log_flex_fallback(error)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **self._flex_fallback_kwargs(kwargs))

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except APIError as error:
            if self.service_tier != "flex" or not is_flex_recoverable(error):
                raise
            self._log_flex_fallback(error)
            return await super()._agenerate(
                messages, stop=stop, run_manager=run_manager, **self._flex_fallback_kwargs(kwargs)
            )


def build_langchain_chat_client(
    model: str,
    timeout: float,
    ai_product: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
    service_tier: Literal["flex"] | None = None,
    max_retries: int = 2,
    flex_fallback_timeout: float | None = None,
) -> ChatOpenAI:
    """Return a ChatOpenAI client for the labeling/report agents. Cloud/DEBUG only.

    Routes through the internal Go ai-gateway when configured; on a misconfiguration the shared
    resolver logs and returns None, so this falls back to direct OpenAI rather than failing the
    call. In gateway mode the bearer selects the capture project, while ``distinct_id`` attributes
    the generation to the customer user or team. The other observability arguments correlate every
    model call in one agent invocation.
    """
    if not settings.DEBUG and not is_cloud():
        raise ApplicationError(
            "AI features are only available in PostHog Cloud",
            type=AI_FEATURES_CLOUD_ONLY_ERROR_TYPE,
            non_retryable=True,
        )

    gateway = resolve_ai_gateway_config()
    if gateway:
        return FlexFirstChatOpenAI(
            model=model,
            api_key=gateway.api_key,
            base_url=gateway.url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=ai_gateway_headers(
                ai_product=ai_product,
                trace_id=trace_id,
                session_id=session_id,
                properties=properties,
                distinct_id=distinct_id,
            ),
            # trust_env=False keeps the in-cluster gateway call off the egress proxy.
            http_client=httpx.Client(trust_env=False),
            http_async_client=httpx.AsyncClient(trust_env=False),
            service_tier=service_tier,
            flex_fallback_timeout=flex_fallback_timeout,
        )

    direct_key = os.environ.get("OPENAI_API_KEY")
    if not direct_key:
        raise Exception("OPENAI_API_KEY is not configured")
    return FlexFirstChatOpenAI(
        model=model,
        api_key=direct_key,
        timeout=timeout,
        max_retries=max_retries,
        service_tier=service_tier,
        flex_fallback_timeout=flex_fallback_timeout,
    )


def build_langchain_callbacks(
    *,
    distinct_id: str,
    trace_id: str,
    session_id: str,
    ai_product: str,
    properties: Mapping[str, str] | None = None,
) -> list[BaseCallbackHandler]:
    # The Go gateway captures $ai_generation itself, so attaching the SDK callback in gateway
    # mode would double-count every model call.
    if not posthoganalytics.default_client or resolve_ai_gateway_config() is not None:
        return []

    callback_properties = dict(properties or {})
    callback_properties["ai_product"] = ai_product
    callback_properties["$ai_session_id"] = session_id
    return [
        CallbackHandler(
            posthoganalytics.default_client,
            distinct_id=distinct_id,
            trace_id=trace_id,
            properties=callback_properties,
        )
    ]
