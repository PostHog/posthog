from typing import Literal

from django.conf import settings

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI, OpenAI

Product = Literal[
    "llm_gateway",
    "posthog_code",
    "background_agents",
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
]  # If you add a product here, make sure it's also in services/llm-gateway/src/llm_gateway/products/config.py


def _team_id_header(team_id: int) -> dict[str, str]:
    return {"x-posthog-property-team_id": str(team_id)}


_ADMIN_SECRET_HEADER = "x-llm-gateway-admin-secret"
_ADMIN_TIMEOUT_SECONDS = 10.0


class GatewayAdminError(Exception):
    """Raised when an LLM gateway admin call is not configured or fails."""


def _admin_base_url() -> str:
    if not settings.LLM_GATEWAY_URL:
        raise GatewayAdminError("LLM_GATEWAY_URL is not configured")
    if not settings.LLM_GATEWAY_ADMIN_SECRET:
        raise GatewayAdminError("LLM_GATEWAY_ADMIN_SECRET is not configured")
    return f"{settings.LLM_GATEWAY_URL.rstrip('/')}/v1/admin"


def get_posthog_code_usage(user_id: int) -> dict:
    """Read a user's live posthog_code cost counters from the gateway.

    Calls the gateway's staff admin endpoint (the rate-limit counters live in the
    gateway's own Redis, unreachable from Django directly). Raises GatewayAdminError
    when the gateway URL / admin secret is not configured.
    """
    url = f"{_admin_base_url()}/usage/{user_id}"
    with httpx.Client(trust_env=False, timeout=_ADMIN_TIMEOUT_SECONDS) as client:
        response = client.get(url, headers={_ADMIN_SECRET_HEADER: settings.LLM_GATEWAY_ADMIN_SECRET})
        response.raise_for_status()
        return response.json()


def reset_posthog_code_usage(
    user_id: int,
    *,
    reset_cost: bool = True,
    reset_product_total: bool = False,
    dry_run: bool = False,
) -> dict:
    """Reset a user's posthog_code cost limits via the gateway's staff admin endpoint.

    `reset_cost` clears the live per-user cost counters. `reset_product_total` clears
    the shared product-wide cost pool — affects every user, so it is opt-in. Raises
    GatewayAdminError when the gateway URL / admin secret is not configured.
    """
    url = f"{_admin_base_url()}/reset/{user_id}"
    payload = {
        "cost": reset_cost,
        "product_total": reset_product_total,
        "dry_run": dry_run,
    }
    with httpx.Client(trust_env=False, timeout=_ADMIN_TIMEOUT_SECONDS) as client:
        response = client.post(url, headers={_ADMIN_SECRET_HEADER: settings.LLM_GATEWAY_ADMIN_SECRET}, json=payload)
        response.raise_for_status()
        return response.json()


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


def get_async_anthropic_gateway_client(product: Product = "django", team_id: int | None = None) -> AsyncAnthropic:
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
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}"
    return AsyncAnthropic(
        base_url=base_url,
        api_key=settings.LLM_GATEWAY_API_KEY,
        default_headers=_team_id_header(team_id) if team_id is not None else None,
        http_client=httpx.AsyncClient(trust_env=False),
    )
