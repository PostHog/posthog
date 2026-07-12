import json
from typing import Literal
from urllib.parse import urlparse

from django.conf import settings

import httpx
import structlog
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI, OpenAI

logger = structlog.get_logger(__name__)

Product = Literal[
    "llm_gateway",
    "ci",
    "posthog_code",
    "background_agents",
    "slack_app",
    "slack_app_routing",
    "wizard",
    "django",
    "growth",
    "llma_translation",
    "llma_summarization",
    "llma_eval_summary",
    "slack-twig",
    "customer_archetype_classification",
    "product_analytics",
    "subscriptions",
    "signals",
    "conversations",
    "warehouse_semantic_enrichment",
    "warehouse_custom_source_builder",
    "stamphog",
]  # If you add a product here, make sure it's also in services/llm-gateway/src/llm_gateway/products/config.py


def _team_id_header(team_id: int) -> dict[str, str]:
    return {"x-posthog-property-team_id": str(team_id)}


def get_llm_client(product: Product = "django", team_id: int | None = None) -> OpenAI:
    """
    Get an OpenAI-compatible client for the internal LLM gateway.

    The gateway exposes an OpenAI Chat Completions API but routes to any backend —
    Anthropic, OpenAI, OpenRouter, Fireworks AI — so callers can pass Claude, GPT,
    or other model IDs through the same interface.

    ## Per-team attribution (`team_id`)

    The gateway authenticates with a single shared personal API key (`LLM_GATEWAY_API_KEY`),
    so by default every captured `$ai_generation` event is attributed to the key owner's team.
    Pass `team_id` to attribute spend to a specific customer team instead: it is sent as a
    default `x-posthog-property-team_id` header on every request, and the usage reporter
    aggregates per-team LLM spend by reading `JSONExtractInt(properties, 'team_id')` (see
    `posthog/tasks/usage_report.py`). Omit it to keep the key owner's team (the prior behavior).

    ## Per-call extras

    `ai_product` and `$ai_billable` are owned by the gateway product config (the route
    sets `ai_product` from `product`, and `$ai_billable` from that product's `billable`
    flag). Do NOT override them via headers — a typo would silently mis-bill or
    misattribute the generation.

    For genuinely per-call tags (source-specific metadata, etc.), pass
    `extra_headers={"x-posthog-property-<key>": "<value>"}` on the individual
    `chat.completions.create(...)` call. Pass the user's distinct_id as `user=` for
    rate limiting and per-user analytics breakdown.

    Example:
        client = get_llm_client(product="signals", team_id=team.id)
        response = client.chat.completions.create(
            model="claude-haiku-4-5",
            messages=[...],
            user=f"team-{team.id}",
            extra_headers={
                "x-posthog-property-source_product": "zendesk",
            },
        )

    Args:
        product: Product tag for the gateway route — used for filtering traces by `ai_product`
            and for per-product rate-limit / model-restriction policies on the gateway.
            Must be one of the values in the `Product` literal above and registered in
            `services/llm-gateway/src/llm_gateway/products/config.py`.
        team_id: Optional PostHog team to attribute the captured `$ai_generation` event to.
            When provided, sent on every request as the `x-posthog-property-team_id` header;
            when omitted, the event is attributed to the gateway key owner's team.
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
    return OpenAI(
        base_url=base_url,
        api_key=settings.LLM_GATEWAY_API_KEY,
        default_headers=_team_id_header(team_id) if team_id is not None else None,
        http_client=httpx.Client(trust_env=False),
    )


def get_async_llm_client(product: Product = "django", team_id: int | None = None) -> AsyncOpenAI:
    """
    Async variant of `get_llm_client`. See `get_llm_client` for the rationale on `team_id`
    attribution and how to attach extra per-call event properties.
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
    return AsyncOpenAI(
        base_url=base_url,
        api_key=settings.LLM_GATEWAY_API_KEY,
        default_headers=_team_id_header(team_id) if team_id is not None else None,
        http_client=httpx.AsyncClient(trust_env=False),
    )


def get_async_anthropic_gateway_client(
    product: Product = "django",
    team_id: int | None = None,
    use_bedrock_fallback: bool = False,
) -> AsyncAnthropic:
    """
    Get an Anthropic-native async client pointed at the internal LLM gateway.

    Prefer this over `get_async_llm_client` when you're calling an Anthropic model and want
    Anthropic-native request features — assistant prefilling, extended thinking, a top-level
    `system` prompt. The gateway exposes a native Messages endpoint (`/{product}/v1/messages`)
    that honours the same per-team attribution headers as the OpenAI Chat Completions route, so
    you get all of that without forcing the request through the OpenAI shape.

    Returns a plain `anthropic.AsyncAnthropic`, NOT `posthoganalytics.ai.anthropic.AsyncAnthropic`:
    the gateway captures the `$ai_generation` event itself, so wrapping the client would
    double-capture (and, for billable products, double-bill) every generation.

    The Anthropic SDK posts to `{base_url}/v1/messages` and authenticates via the `x-api-key`
    header, both of which the gateway accepts. See `get_llm_client` for the `team_id` attribution
    rationale — it is sent identically as a default `x-posthog-property-team_id` header. For
    per-call tags, pass `extra_headers={"x-posthog-property-<key>": "<value>"}` on the individual
    `messages.create(...)` call, and the user identifier as `metadata={"user_id": ...}`.

    Set `use_bedrock_fallback=True` to opt into the gateway's Bedrock fallback: if Anthropic
    returns a 5xx/429 (or its circuit breaker is open) the gateway retries the request against
    Bedrock instead of failing. Sent as the `x-posthog-use-bedrock-fallback` default header.
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    default_headers = _team_id_header(team_id) if team_id is not None else {}
    if use_bedrock_fallback:
        default_headers["x-posthog-use-bedrock-fallback"] = "true"

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}"
    return AsyncAnthropic(
        base_url=base_url,
        api_key=settings.LLM_GATEWAY_API_KEY,
        default_headers=default_headers or None,
        http_client=httpx.AsyncClient(trust_env=False),
    )


def _gateway_misconfig(url: str, api_key: str) -> str | None:
    """Return a reason string if the gateway env is half-applied or malformed, else None."""
    if not (url and api_key):
        return "AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be set together"
    # The SDK appends /chat/completions, so base_url must already carry the /v1 path.
    if not urlparse(url).path.rstrip("/").endswith("/v1"):
        return "AI_GATEWAY_URL must include the OpenAI base path, e.g. https://<host>/v1"
    return None


def resolve_ai_gateway_config() -> tuple[str, str] | None:
    """Return the validated (url, api_key) for the internal Go ai-gateway, or None.

    None when neither env var is set (the caller uses its normal path), and ALSO when the config
    is half-applied or the URL is malformed: that logs a warning and returns None so the caller
    falls back to the current flow rather than failing the call (the fallback comes out once
    rollout completes).
    """
    url, api_key = settings.AI_GATEWAY_URL, settings.AI_GATEWAY_API_KEY
    if not (url or api_key):
        return None
    misconfig = _gateway_misconfig(url, api_key)
    if misconfig:
        logger.warning("ai_gateway_misconfigured_falling_back", reason=misconfig)
        return None
    return url, api_key


def ai_product_headers(ai_product: str | None) -> dict[str, str] | None:
    """X-PostHog-Properties header tagging the captured generation with its AIO product.

    The slugless Go gateway has no product route, so callers pass the product here to keep
    per-product attribution on the shared ``phs_`` token. Don't use a ``$ai_`` prefix — the
    gateway strips those as reserved.
    """
    if not ai_product:
        return None
    return {"X-PostHog-Properties": json.dumps({"ai_product": ai_product})}


def build_openai_client(product: Product, ai_product: str | None = None) -> OpenAI:
    """Return a raw OpenAI client routed through the internal Go ai-gateway when configured,
    else the Python LLM gateway via :func:`get_llm_client`.

    ``product`` names the Python-gateway route used in the fallback; the slugless Go gateway
    derives the team from its ``phs_`` bearer and ignores it. ``ai_product`` tags the captured
    generation in gateway mode (the Python-gateway fallback derives the tag from ``product``).
    trust_env=False keeps the in-cluster call off the egress proxy.
    """
    gateway = resolve_ai_gateway_config()
    if gateway:
        url, api_key = gateway
        return OpenAI(
            api_key=api_key,
            base_url=url,
            default_headers=ai_product_headers(ai_product),
            http_client=httpx.Client(trust_env=False),
        )
    return get_llm_client(product)


def build_async_openai_client(product: Product, ai_product: str | None = None) -> AsyncOpenAI:
    """Async variant of :func:`build_openai_client`."""
    gateway = resolve_ai_gateway_config()
    if gateway:
        url, api_key = gateway
        return AsyncOpenAI(
            api_key=api_key,
            base_url=url,
            default_headers=ai_product_headers(ai_product),
            http_client=httpx.AsyncClient(trust_env=False),
        )
    return get_async_llm_client(product)
