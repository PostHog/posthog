"""OpenAI-compatible client for the cluster-labeling agents, routed through the
ai-gateway when AI_GATEWAY_URL + AI_GATEWAY_API_KEY are set, else direct to OpenAI."""

import os
from urllib.parse import urlparse

from django.conf import settings

import httpx
from langchain_openai import ChatOpenAI

from posthog.cloud_utils import is_cloud


def build_openai_chat_client(model: str, timeout: float) -> ChatOpenAI:
    """Return a ChatOpenAI client for cluster labeling. Cloud/DEBUG only.

    In gateway mode the ``phs_`` bearer is team-scoped, so no per-team header is needed.
    """
    if not settings.DEBUG and not is_cloud():
        raise Exception("AI features are only available in PostHog Cloud")

    url, api_key = settings.AI_GATEWAY_URL, settings.AI_GATEWAY_API_KEY
    if url or api_key:
        if not (url and api_key):
            raise Exception("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be set together")
        # The SDK appends /chat/completions, so base_url must already carry the /v1 path.
        if not urlparse(url).path.rstrip("/").endswith("/v1"):
            raise Exception("AI_GATEWAY_URL must include the OpenAI base path, e.g. https://<host>/v1")
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=url,
            timeout=timeout,
            max_retries=2,
            # trust_env=False keeps the in-cluster gateway call off the egress proxy.
            http_client=httpx.Client(trust_env=False),
            http_async_client=httpx.AsyncClient(trust_env=False),
        )

    direct_key = os.environ.get("OPENAI_API_KEY")
    if not direct_key:
        raise Exception("OPENAI_API_KEY is not configured")
    return ChatOpenAI(model=model, api_key=direct_key, timeout=timeout, max_retries=2)
