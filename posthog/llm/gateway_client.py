from typing import Literal

from django.conf import settings

import httpx
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
    "slack-posthog-code",
    "product_analytics",
    "subscriptions",
    "signals",
]  # If you add a product here, make sure it's also in services/llm-gateway/src/llm_gateway/products/config.py


def _team_id_header(team_id: int) -> dict[str, str]:
    return {"x-posthog-property-team_id": str(team_id)}


def get_llm_client(*, product: Product, team_id: int) -> OpenAI:
    """
    Get an OpenAI-compatible client for the internal LLM gateway.

    The gateway exposes an OpenAI Chat Completions API but routes to any backend —
    Anthropic, OpenAI, OpenRouter, Fireworks AI — so callers can pass Claude, GPT,
    or other model IDs through the same interface.

    ## Why `team_id` is required

    The gateway authenticates with a single shared personal API key (`LLM_GATEWAY_API_KEY`),
    so every captured `$ai_generation` event lands in the key owner's team unless the
    request injects an explicit team override via `x-posthog-property-team_id`. The
    usage reporter aggregates per-team LLM spend by reading
    `JSONExtractInt(properties, 'team_id')` (see `posthog/tasks/usage_report.py`),
    so omitting this header silently breaks per-customer-team cost rollups.

    This helper attaches `x-posthog-property-team_id` as a default header on every
    request made through the returned client, mirroring how MaxAI threads the same
    value through LangChain metadata (`ee/hogai/llm.py` — `MaxChatMixin._with_posthog_properties`).

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
        team_id: The PostHog team to attribute the captured `$ai_generation` event to.
            Sent on every request as the `x-posthog-property-team_id` header.
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
    return OpenAI(
        base_url=base_url,
        api_key=settings.LLM_GATEWAY_API_KEY,
        default_headers=_team_id_header(team_id),
        http_client=httpx.Client(trust_env=False),
    )


def get_async_llm_client(*, product: Product, team_id: int) -> AsyncOpenAI:
    """
    Async variant of `get_llm_client`. See `get_llm_client` for the full rationale on
    why `team_id` is required and how to attach extra per-call event properties.
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
    return AsyncOpenAI(
        base_url=base_url,
        api_key=settings.LLM_GATEWAY_API_KEY,
        default_headers=_team_id_header(team_id),
        http_client=httpx.AsyncClient(trust_env=False),
    )
