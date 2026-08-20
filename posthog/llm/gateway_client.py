import json
from collections.abc import Mapping
from dataclasses import field
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID, uuid5

from django.conf import settings

import httpx
import structlog
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI, OpenAI

from posthog.dataclasses import frozen

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
    "review_hog",
    "custom_image_scans",
    "conversations",
    "warehouse_semantic_enrichment",
    "warehouse_custom_source_builder",
    "web_analytics",
    "stamphog",
]  # If you add a product here, make sure it's also in services/llm-gateway/src/llm_gateway/products/config.py


def _team_id_header(team_id: int) -> dict[str, str]:
    return {"x-posthog-property-team_id": str(team_id)}


def team_distinct_id(team_id: int) -> str:
    """Namespace team-owned work away from bare numeric user distinct IDs."""
    return f"team-{team_id}"


def get_llm_client(
    product: Product = "django",
    team_id: int | None = None,
    api_key: str | None = None,
    default_headers: Mapping[str, str] | None = None,
) -> OpenAI:
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
        api_key: Optional short-lived credential to use instead of `LLM_GATEWAY_API_KEY`.
            Server-only products use this to avoid exposing the shared personal API key.
        default_headers: Optional headers sent with every request. Product-owned headers such as
            team attribution override values supplied here.
    """
    resolved_api_key = api_key or settings.LLM_GATEWAY_API_KEY
    if not settings.LLM_GATEWAY_URL or not resolved_api_key:
        raise ValueError("LLM_GATEWAY_URL and an API key must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
    headers = dict(default_headers or {})
    if team_id is not None:
        headers.update(_team_id_header(team_id))

    return OpenAI(
        base_url=base_url,
        api_key=resolved_api_key,
        default_headers=headers or None,
        http_client=httpx.Client(trust_env=False),
    )


def get_async_llm_client(
    product: Product = "django",
    team_id: int | None = None,
    default_headers: Mapping[str, str] | None = None,
) -> AsyncOpenAI:
    """
    Async variant of `get_llm_client`. See `get_llm_client` for the rationale on `team_id`
    attribution and how to attach extra per-call event properties.
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
    headers = dict(default_headers or {})
    if team_id is not None:
        headers.update(_team_id_header(team_id))

    return AsyncOpenAI(
        base_url=base_url,
        api_key=settings.LLM_GATEWAY_API_KEY,
        default_headers=headers or None,
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


@frozen
class AIGatewayConfig:
    url: str
    api_key: str = field(repr=False)


def resolve_ai_gateway_config() -> AIGatewayConfig | None:
    """Return the validated AIGatewayConfig for the internal Go ai-gateway, or None.

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
    return AIGatewayConfig(url=url, api_key=api_key)


def _ai_property_headers(**labels: str | None) -> dict[str, str] | None:
    """Build the ``X-PostHog-Properties`` header from caller labels, dropping unset ones.

    The slugless Go gateway reads event labels only from this JSON blob, not from the
    ``x-posthog-property-<key>`` per-header form the Python gateway accepts. Don't use a
    ``$ai_`` prefix on a key: the gateway strips those as reserved. Returns None when no
    label is set so the client sends no properties header.
    """
    set_labels = {key: value for key, value in labels.items() if value}
    if not set_labels:
        return None
    return {"X-PostHog-Properties": json.dumps(set_labels)}


def ai_gateway_headers(
    *,
    ai_product: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
) -> dict[str, str] | None:
    """Build the Go ai-gateway headers that correlate a multi-call AI operation."""
    labels = dict(properties or {})
    if ai_product:
        labels["ai_product"] = ai_product

    headers = _ai_property_headers(**labels) or {}
    if trace_id:
        headers["X-PostHog-Trace-Id"] = trace_id
    if session_id:
        headers["X-PostHog-Session-Id"] = session_id
    if distinct_id:
        headers["X-PostHog-Distinct-Id"] = distinct_id
    return headers or None


# Mirrors the namespace in services/llm-gateway/src/llm_gateway/callbacks/posthog.py. Both must
# stay equal or a team's trace id changes with whichever gateway serves it.
_TEAM_TRACE_ID_NAMESPACE = UUID("8d4f6b7e-6a3e-4f3a-9f3b-3b6f4d2e8a1a")


def _python_gateway_observability_headers(
    trace_id: str | None,
    session_id: str | None,
    properties: Mapping[str, str] | None,
) -> dict[str, str] | None:
    headers = {f"x-posthog-property-{key}": value for key, value in (properties or {}).items()}
    if session_id:
        headers["x-posthog-property-$ai_session_id"] = session_id
    if trace_id:
        try:
            normalized_trace_id = UUID(trace_id)
        except ValueError:
            normalized_trace_id = uuid5(_TEAM_TRACE_ID_NAMESPACE, trace_id)
        span_id = uuid5(_TEAM_TRACE_ID_NAMESPACE, f"span-{trace_id}").hex[:16]
        headers["traceparent"] = f"00-{normalized_trace_id.hex}-{span_id}-01"
    return headers or None


def team_trace_id(team_id: int | None) -> str | None:
    """Deterministic ``$ai_trace_id`` for a team, or None when unattributed.

    Absent an ``X-PostHog-Trace-Id`` header the Go gateway stamps a fresh id per request, leaving
    every generation in its own trace. Grouping is per team, not per pipeline run.
    """
    if team_id is None:
        return None
    return str(uuid5(_TEAM_TRACE_ID_NAMESPACE, f"team-{team_id}"))


def _ai_trace_headers(team_id: int | None) -> dict[str, str]:
    """``X-PostHog-Trace-Id`` header for a team; empty (not None) so callers can splat it."""
    trace_id = team_trace_id(team_id)
    return {"X-PostHog-Trace-Id": trace_id} if trace_id else {}


def _anthropic_gateway_base_url(openai_base_url: str) -> str:
    """Drop the OpenAI ``/v1`` suffix so the Anthropic SDK, which appends ``/v1/messages``
    itself, hits the same gateway root the OpenAI route uses. ``resolve_ai_gateway_config``
    guarantees the ``/v1`` suffix, so this is the inverse of that validation.
    """
    trimmed = openai_base_url.rstrip("/")
    if trimmed.endswith("/v1"):
        trimmed = trimmed[: -len("/v1")]
    return trimmed


def build_openai_client(
    product: Product,
    ai_product: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
) -> OpenAI:
    """Return a raw OpenAI client routed through the internal Go ai-gateway when configured,
    else the Python LLM gateway via :func:`get_llm_client`.

    ``product`` names the Python-gateway route used in the fallback; the slugless Go gateway
    derives the team from its ``phs_`` bearer and ignores it. ``ai_product`` tags the captured
    generation in gateway mode (the Python-gateway fallback derives the tag from ``product``).
    ``distinct_id`` is a Go-gateway header only. Callers must also pass the same value as ``user``
    on every completion request so the Python-gateway fallback preserves end-user attribution.
    trust_env=False keeps the in-cluster call off the egress proxy.
    """
    gateway = resolve_ai_gateway_config()
    if gateway:
        return OpenAI(
            api_key=gateway.api_key,
            base_url=gateway.url,
            default_headers=ai_gateway_headers(
                ai_product=ai_product,
                trace_id=trace_id,
                session_id=session_id,
                properties=properties,
                distinct_id=distinct_id,
            ),
            http_client=httpx.Client(trust_env=False),
        )
    fallback_headers = _python_gateway_observability_headers(trace_id, session_id, properties)
    return get_llm_client(product, default_headers=fallback_headers)


def build_async_openai_client(
    product: Product,
    ai_product: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
) -> AsyncOpenAI:
    """Async variant of :func:`build_openai_client`."""
    gateway = resolve_ai_gateway_config()
    if gateway:
        return AsyncOpenAI(
            api_key=gateway.api_key,
            base_url=gateway.url,
            default_headers=ai_gateway_headers(
                ai_product=ai_product,
                trace_id=trace_id,
                session_id=session_id,
                properties=properties,
                distinct_id=distinct_id,
            ),
            http_client=httpx.AsyncClient(trust_env=False),
        )
    fallback_headers = _python_gateway_observability_headers(trace_id, session_id, properties)
    return get_async_llm_client(product, default_headers=fallback_headers)


def build_async_anthropic_client(
    product: Product,
    ai_product: str | None = None,
    ai_stage: str | None = None,
    team_id: int | None = None,
    use_bedrock_fallback: bool = False,
) -> AsyncAnthropic:
    """Return a raw Anthropic client routed through the internal Go ai-gateway when configured,
    else the Python LLM gateway via :func:`get_async_anthropic_gateway_client`.

    In gateway mode the ``ai_product``, ``ai_stage``, and ``team_id`` labels ride on the
    ``X-PostHog-Properties`` JSON blob: the Go gateway ignores the ``x-posthog-property-<key>``
    per-header form the Python gateway reads, so they would be dropped if passed that way.
    ``team_id`` is the customer team the generation is attributed to (the usage report reads it as
    a property); it does not change the event's owning project, which the gateway derives from the
    ``phs_`` bearer. The Anthropic SDK appends ``/v1/messages``, so the client gets the gateway
    root rather than the ``/v1`` OpenAI base.

    ``use_bedrock_fallback`` only affects the Python-gateway fallback path; the Go gateway fails
    over to Bedrock on its own via the host breaker and reads no opt-in header. trust_env=False
    keeps the in-cluster call off the egress proxy.

    An attributed call also carries ``X-PostHog-Trace-Id`` (see :func:`team_trace_id`); the
    Python-gateway fallback derives the same id internally and needs no header.
    """
    gateway = resolve_ai_gateway_config()
    if gateway:
        default_headers = {
            **(
                _ai_property_headers(
                    ai_product=ai_product,
                    ai_stage=ai_stage,
                    team_id=str(team_id) if team_id is not None else None,
                )
                or {}
            ),
            **_ai_trace_headers(team_id),
        }
        return AsyncAnthropic(
            api_key=gateway.api_key,
            base_url=_anthropic_gateway_base_url(gateway.url),
            default_headers=default_headers or None,
            http_client=httpx.AsyncClient(trust_env=False),
        )
    return get_async_anthropic_gateway_client(product, team_id=team_id, use_bedrock_fallback=use_bedrock_fallback)
