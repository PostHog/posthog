"""ChatOpenAI client for the labeling/report agents, routed through the internal
Go ai-gateway when AI_GATEWAY_URL + AI_GATEWAY_API_KEY are set, else direct to OpenAI.

The raw-SDK builders for summarization live in ``posthog.llm.gateway_client`` (importing
from this package would pull in the temporal workflow graph and cycle); this module shares
its ``resolve_ai_gateway_config`` validator and ``ai_gateway_headers`` helper.
"""

import os
from collections.abc import Mapping

from django.conf import settings

import httpx
import posthoganalytics
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from temporalio.exceptions import ApplicationError

from posthog.cloud_utils import is_cloud
from posthog.llm.gateway_client import ai_gateway_headers, resolve_ai_gateway_config

# On a non-cloud, non-DEBUG deployment there is no AI gateway, so this guard fails identically
# every run. The interceptor in posthog/temporal/common/posthog_client.py keeps this error type
# out of error tracking. Raised non-retryably so a stray execution stops on the first attempt.
AI_FEATURES_CLOUD_ONLY_ERROR_TYPE = "AIFeaturesCloudOnly"


def build_langchain_chat_client(
    model: str,
    timeout: float,
    ai_product: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
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
        return ChatOpenAI(
            model=model,
            api_key=gateway.api_key,
            base_url=gateway.url,
            timeout=timeout,
            max_retries=2,
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
        )

    direct_key = os.environ.get("OPENAI_API_KEY")
    if not direct_key:
        raise Exception("OPENAI_API_KEY is not configured")
    return ChatOpenAI(model=model, api_key=direct_key, timeout=timeout, max_retries=2)


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
