"""OpenAI-compatible client for the cluster-labeling agents, routed through the
ai-gateway when AI_GATEWAY_URL + AI_GATEWAY_API_KEY are set, else direct to OpenAI."""

import os
import json
from urllib.parse import urlparse

from django.conf import settings

import httpx
import structlog
from langchain_openai import ChatOpenAI

from posthog.cloud_utils import is_cloud

logger = structlog.get_logger(__name__)


def build_langchain_chat_client(model: str, timeout: float, ai_product: str | None = None) -> ChatOpenAI:
    """Return a ChatOpenAI client for cluster labeling. Cloud/DEBUG only.

    Routes through the ai-gateway when AI_GATEWAY_URL + AI_GATEWAY_API_KEY are both set and the
    URL is well-formed; on a misconfiguration it logs and falls back to direct OpenAI so a
    half-applied rollout config can't break labeling. In gateway mode the ``phs_`` bearer is
    team-scoped, so no per-team header is needed; ``ai_product`` (when given) tags the captured
    ``$ai_generation`` event via the gateway's ``X-PostHog-Properties`` header.
    """
    if not settings.DEBUG and not is_cloud():
        raise Exception("AI features are only available in PostHog Cloud")

    url, api_key = settings.AI_GATEWAY_URL, settings.AI_GATEWAY_API_KEY
    if url or api_key:
        misconfig = _gateway_misconfig(url, api_key)
        if misconfig:
            logger.warning("ai_gateway_misconfigured_falling_back", reason=misconfig)
        else:
            return ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=url,
                timeout=timeout,
                max_retries=2,
                default_headers=_ai_product_headers(ai_product),
                # trust_env=False keeps the in-cluster gateway call off the egress proxy.
                http_client=httpx.Client(trust_env=False),
                http_async_client=httpx.AsyncClient(trust_env=False),
            )

    direct_key = os.environ.get("OPENAI_API_KEY")
    if not direct_key:
        raise Exception("OPENAI_API_KEY is not configured")
    return ChatOpenAI(model=model, api_key=direct_key, timeout=timeout, max_retries=2)


def _gateway_misconfig(url: str, api_key: str) -> str | None:
    """Return a reason string if the gateway env is half-applied or malformed, else None."""
    if not (url and api_key):
        return "AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be set together"
    # The SDK appends /chat/completions, so base_url must already carry the /v1 path.
    if not urlparse(url).path.rstrip("/").endswith("/v1"):
        return "AI_GATEWAY_URL must include the OpenAI base path, e.g. https://<host>/v1"
    return None


def _ai_product_headers(ai_product: str | None) -> dict[str, str] | None:
    """X-PostHog-Properties header tagging the captured generation with its AIO product."""
    if not ai_product:
        return None
    return {"X-PostHog-Properties": json.dumps({"ai_product": ai_product})}
