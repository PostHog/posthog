"""ChatOpenAI client for the labeling/report agents, routed through the internal
Go ai-gateway when AI_GATEWAY_URL + AI_GATEWAY_API_KEY are set, else direct to OpenAI.

The raw-SDK builders for summarization live in ``posthog.llm.gateway_client`` (importing
from this package would pull in the temporal workflow graph and cycle); this module shares
its ``resolve_ai_gateway_config`` validator and ``ai_gateway_headers`` helper.
"""

import os
import time
from collections.abc import Mapping
from typing import Any, Literal

from django.conf import settings

import httpx
import structlog
import posthoganalytics
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.callbacks.manager import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI
from openai import APIError, RateLimitError
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from pydantic import PrivateAttr
from temporalio.exceptions import ApplicationError

from posthog.cloud_utils import is_cloud
from posthog.llm.gateway_client import ai_gateway_headers, resolve_ai_gateway_config
from posthog.llm.openai_flex import FLEX_CAPABLE_MODELS, is_flex_recoverable

logger = structlog.get_logger(__name__)

# On a non-cloud, non-DEBUG deployment there is no AI gateway, so this guard fails identically
# every run. The interceptor in posthog/temporal/common/posthog_client.py keeps this error type
# out of error tracking. Raised non-retryably so a stray execution stops on the first attempt.
AI_FEATURES_CLOUD_ONLY_ERROR_TYPE = "AIFeaturesCloudOnly"


FLEX_REPROBE_COOLDOWN = 60.0


class FlexFirstChatOpenAI(ChatOpenAI):
    """ChatOpenAI that retries a failed flex call once on the standard tier, per call.

    The openai SDK's retry loop re-sends the byte-identical request, so it can only
    re-roll a flex capacity refusal. This override retries just the failing chat
    completion with service_tier="default", so an agent loop keeps its completed
    turns instead of rerunning from scratch. Build flex clients with max_retries=0:
    the tier switch is the retry.

    A fallback then holds the client on standard, because retrying a tier that just
    refused wastes a call. How long it holds depends on what the tier cost to discover:
    a capacity refusal pauses flex for ``FLEX_REPROBE_COOLDOWN`` and the run probes it
    again, while a stall or a connection failure, which costs a full timeout to find,
    latches the client for the rest of the run.

    Build one through ``build_flex_first_chat_client`` rather than directly, so every
    caller gets the same tier, timeout, and retry policy.
    """

    _flex_latched: bool = PrivateAttr(default=False)
    _flex_paused_until: float = PrivateAttr(default=0.0)
    _flex_this_call: bool = PrivateAttr(default=False)

    def _flex_available(self) -> bool:
        return self.service_tier == "flex" and not self._flex_latched and time.monotonic() >= self._flex_paused_until

    def _get_request_payload(self, input_: LanguageModelInput, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        if self.service_tier == "flex" and not self._flex_this_call:
            kwargs = {**kwargs, "service_tier": "default"}
        return super()._get_request_payload(input_, stop=stop, **kwargs)

    def _latch_or_raise(self, error: APIError) -> None:
        # Only a call that actually went out as flex has a standard tier left to try.
        if not self._flex_this_call or not is_flex_recoverable(error):
            raise error
        if isinstance(error, RateLimitError):
            self._flex_paused_until = time.monotonic() + FLEX_REPROBE_COOLDOWN
        else:
            self._flex_latched = True
        logger.warning(
            "flex_call_fell_back",
            error_type=type(error).__name__,
            status_code=getattr(error, "status_code", None),
            model=self.model_name,
            latched=self._flex_latched,
        )
        self._flex_this_call = False

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._flex_this_call = self._flex_available()
        try:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except APIError as error:
            self._latch_or_raise(error)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._flex_this_call = self._flex_available()
        try:
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except APIError as error:
            self._latch_or_raise(error)
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)


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
        )

    direct_key = os.environ.get("OPENAI_API_KEY")
    if not direct_key:
        raise Exception("OPENAI_API_KEY is not configured")
    return FlexFirstChatOpenAI(
        model=model, api_key=direct_key, timeout=timeout, max_retries=max_retries, service_tier=service_tier
    )


# Per-call timeouts, capped so no single call can outlive the activity that runs the agent:
# flex 120s x 1 attempt (the standard-tier fallback call is the retry), standard 240s x 2
# attempts. The ai-gateway cuts non-streaming calls at ~290s, so longer client timeouts are
# unreachable.
FLEX_CALL_TIMEOUT = 120.0
STANDARD_CALL_TIMEOUT = 240.0


def build_flex_first_chat_client(
    model: str,
    timeout: float,
    *,
    ai_product: str,
    trace_id: str,
    session_id: str,
    properties: Mapping[str, str],
    distinct_id: str,
    flex: bool = True,
) -> ChatOpenAI:
    """Return a ChatOpenAI client that prefers the flex service tier.

    The langchain agents behind this helper all run as scheduled batches with no user
    waiting, so an allowlisted model requests flex for half-price tokens and
    ``FlexFirstChatOpenAI`` retries a failed flex call on the standard tier.

    A model outside the allowlist keeps the standard tier, because OpenAI decides flex
    eligibility per model and the gpt-4.1 family rejects the service_tier field outright.
    Pass ``flex=False`` to opt a caller out while keeping the bounded timeouts.
    """
    use_flex = flex and model in FLEX_CAPABLE_MODELS
    return build_langchain_chat_client(
        model,
        FLEX_CALL_TIMEOUT if use_flex else min(timeout, STANDARD_CALL_TIMEOUT),
        ai_product=ai_product,
        trace_id=trace_id,
        session_id=session_id,
        properties=properties,
        distinct_id=distinct_id,
        service_tier="flex" if use_flex else None,
        max_retries=0 if use_flex else 1,
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
