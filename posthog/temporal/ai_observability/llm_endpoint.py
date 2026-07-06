"""ChatOpenAI client for the labeling/report agents, routed through the internal
Go ai-gateway when AI_GATEWAY_URL + AI_GATEWAY_API_KEY are set, else direct to OpenAI.

The raw-SDK builders for summarization live in ``posthog.llm.gateway_client`` (importing
from this package would pull in the temporal workflow graph and cycle); this module shares
its ``resolve_ai_gateway_config`` validator and ``ai_product_headers`` helper.
"""

import os

from django.conf import settings

import httpx
from langchain_openai import ChatOpenAI

from posthog.cloud_utils import is_cloud
from posthog.llm.gateway_client import ai_product_headers, resolve_ai_gateway_config


def build_langchain_chat_client(model: str, timeout: float, ai_product: str | None = None) -> ChatOpenAI:
    """Return a ChatOpenAI client for the labeling/report agents. Cloud/DEBUG only.

    Routes through the internal Go ai-gateway when configured; on a misconfiguration the shared
    resolver logs and returns None, so this falls back to direct OpenAI rather than failing the
    call. In gateway mode the ``phs_`` bearer is team-scoped, so no per-team header is needed;
    ``ai_product`` (when given) tags the captured ``$ai_generation`` via X-PostHog-Properties.
    """
    if not settings.DEBUG and not is_cloud():
        raise Exception("AI features are only available in PostHog Cloud")

    gateway = resolve_ai_gateway_config()
    if gateway:
        url, api_key = gateway
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=url,
            timeout=timeout,
            max_retries=2,
            default_headers=ai_product_headers(ai_product),
            # trust_env=False keeps the in-cluster gateway call off the egress proxy.
            http_client=httpx.Client(trust_env=False),
            http_async_client=httpx.AsyncClient(trust_env=False),
        )

    direct_key = os.environ.get("OPENAI_API_KEY")
    if not direct_key:
        raise Exception("OPENAI_API_KEY is not configured")
    return ChatOpenAI(model=model, api_key=direct_key, timeout=timeout, max_retries=2)
