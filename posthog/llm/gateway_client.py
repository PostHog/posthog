import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import field
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID, uuid5

from django.conf import settings

import httpx
import structlog
from anthropic import Anthropic, AsyncAnthropic
from google import genai
from google.genai import types as genai_types
from openai import AsyncOpenAI, OpenAI

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

Product = Literal[
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
    "posthog_ai",
    "subscriptions",
    "signals",
    "review_hog",
    "conversations",
    "warehouse_semantic_enrichment",
    "warehouse_custom_source_builder",
    "web_analytics",
]


def team_distinct_id(team_id: int) -> str:
    """Namespace team-owned work away from bare numeric user distinct IDs."""
    return f"team-{team_id}"


class GatewayNotConfiguredError(ValueError):
    """No LLM gateway is configured, so the client could not be built and no call was made.

    A `ValueError` so existing callers keep behaving as before, but a distinct type so a caller whose
    LLM step is optional can tell an absent gateway, which is static and the same for every team,
    apart from a gateway call that went out and failed and is worth reporting.
    """


_private_scout_gateway_token: ContextVar[str | None] = ContextVar("private_scout_gateway_token", default=None)


def ensure_scout_trial_capture_ready() -> None:
    if not getattr(settings, "SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE", False):
        raise GatewayNotConfiguredError("Private capture must be enabled for scout trials on the Go AI gateway")
    if not urlparse(settings.AI_GATEWAY_URL).path.rstrip("/").endswith("/v1"):
        raise GatewayNotConfiguredError("Scout trials require AI_GATEWAY_URL with the /v1 base path")


@contextmanager
def private_scout_gateway(api_key: str) -> Iterator[None]:
    ensure_scout_trial_capture_ready()
    if not api_key.startswith("phe_"):
        raise GatewayNotConfiguredError("Scout trials require AI_GATEWAY_URL and a private scoped Go gateway token")
    token = _private_scout_gateway_token.set(api_key)
    try:
        with private_capture_context():
            yield
    finally:
        _private_scout_gateway_token.reset(token)


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

    None when neither env var is set, and also when the config is half-applied or the URL is
    malformed, which logs a warning. Callers that need a client raise GatewayNotConfiguredError on None.
    """
    trial_token = _private_scout_gateway_token.get()
    if trial_token is not None:
        return AIGatewayConfig(url=settings.AI_GATEWAY_URL, api_key=trial_token)
    url, api_key = settings.AI_GATEWAY_URL, settings.AI_GATEWAY_API_KEY
    if not (url or api_key):
        return None
    misconfig = _gateway_misconfig(url, api_key)
    if misconfig:
        logger.warning("ai_gateway_misconfigured", reason=misconfig)
        return None
    return AIGatewayConfig(url=url, api_key=api_key)


# A plain http URL to these hosts stays on this machine, so local development needs no certificate.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def resolve_https_ai_gateway_config() -> AIGatewayConfig | None:
    """``resolve_ai_gateway_config``, but None when the URL would send the gateway key in clear to
    a host off this machine.

    Use it for a client that puts the key in an ``Authorization`` header itself, instead of through
    an SDK that the caller already pinned to https.
    """
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        return None
    parsed = urlparse(gateway.url)
    if parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
        logger.warning("ai_gateway_url_not_https")
        return None
    return gateway


def _ai_property_headers(**labels: str | None) -> dict[str, str] | None:
    """Build the ``X-PostHog-Properties`` header from caller labels, dropping unset ones.

    The Go gateway reads event labels only from this JSON blob and ignores
    ``x-posthog-property-<key>`` headers. Don't use a
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
    privacy_mode: bool = False,
) -> dict[str, str] | None:
    """Build the Go ai-gateway headers that correlate a multi-call AI operation."""
    labels = dict(properties or {})
    if ai_product:
        labels["ai_product"] = ai_product

    headers = _ai_property_headers(**labels) or {}
    if ai_product:
        headers["X-PostHog-Product"] = ai_product
    if trace_id:
        headers["X-PostHog-Trace-Id"] = trace_id
    if session_id:
        headers["X-PostHog-Session-Id"] = session_id
    if distinct_id:
        headers["X-PostHog-Distinct-Id"] = distinct_id
    if privacy_mode:
        headers["X-PostHog-Privacy-Mode"] = "true"
    return headers or None


# Changing it changes every team's trace id, splitting their generations across two traces.
_TEAM_TRACE_ID_NAMESPACE = UUID("8d4f6b7e-6a3e-4f3a-9f3b-3b6f4d2e8a1a")


def team_trace_id(team_id: int | None) -> str | None:
    """Deterministic ``$ai_trace_id`` for a team, or None when unattributed.

    Absent an ``X-PostHog-Trace-Id`` header the Go gateway stamps a fresh id per request, leaving
    every generation in its own trace. Grouping is per team, not per pipeline run.
    """
    if team_id is None:
        return None
    return str(uuid5(_TEAM_TRACE_ID_NAMESPACE, f"team-{team_id}"))


def trace_id_from_seed(seed: str) -> str:
    """Deterministic ``$ai_trace_id`` for a caller with no run id to borrow.

    Absent a trace id the gateway stamps a fresh one per request, so every call in one
    logical operation lands in a trace of its own. The seed must be unique to the
    operation, because a coarser one merges unrelated calls into a single trace.
    """
    return str(uuid5(_TEAM_TRACE_ID_NAMESPACE, seed))


def anthropic_gateway_base_url(openai_base_url: str) -> str:
    """Drop the OpenAI ``/v1`` suffix so the Anthropic SDK, which appends ``/v1/messages``
    itself, hits the same gateway root the OpenAI route uses. ``resolve_ai_gateway_config``
    guarantees the ``/v1`` suffix, so this is the inverse of that validation. The Gemini SDK
    appends ``/v1beta/models/...`` and needs the same root.
    """
    trimmed = openai_base_url.rstrip("/")
    if trimmed.endswith("/v1"):
        trimmed = trimmed[: -len("/v1")]
    return trimmed


def openai_gateway_configured() -> bool:
    """Whether :func:`build_openai_client` can build a client, without building one."""
    return resolve_ai_gateway_config() is not None


def _require_ai_gateway_config() -> AIGatewayConfig:
    gateway = resolve_ai_gateway_config()
    if gateway is not None:
        return gateway
    url, api_key = settings.AI_GATEWAY_URL, settings.AI_GATEWAY_API_KEY
    if url or api_key:
        misconfig = _gateway_misconfig(url, api_key)
        assert misconfig is not None
        raise GatewayNotConfiguredError(misconfig)
    raise GatewayNotConfiguredError(
        "AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured; locally, enable the `ai_gateway` "
        "dev capability and run bin/setup-gateway-e2e"
    )


def build_openai_client(
    ai_product: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
    privacy_mode: bool = False,
) -> OpenAI:
    """Return a raw OpenAI client routed through the internal Go ai-gateway.

    The gateway derives the team from its ``phs_`` bearer. ``ai_product`` tags the captured generation
    through both the typed product header and the ``X-PostHog-Properties`` blob. Raises
    GatewayNotConfiguredError when the Go ai-gateway pair is unset or malformed.
    trust_env=False keeps the in-cluster call off the egress proxy.
    """
    gateway = _require_ai_gateway_config()
    return OpenAI(
        api_key=gateway.api_key,
        base_url=gateway.url,
        default_headers=ai_gateway_headers(
            ai_product=ai_product,
            trace_id=trace_id,
            session_id=session_id,
            properties=properties,
            distinct_id=distinct_id,
            privacy_mode=privacy_mode,
        ),
        http_client=httpx.Client(trust_env=False),
    )


def build_async_openai_client(
    ai_product: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
    privacy_mode: bool = False,
) -> AsyncOpenAI:
    """Async variant of :func:`build_openai_client`."""
    gateway = _require_ai_gateway_config()
    return AsyncOpenAI(
        api_key=gateway.api_key,
        base_url=gateway.url,
        default_headers=ai_gateway_headers(
            ai_product=ai_product,
            trace_id=trace_id,
            session_id=session_id,
            properties=properties,
            distinct_id=distinct_id,
            privacy_mode=privacy_mode,
        ),
        http_client=httpx.AsyncClient(trust_env=False),
    )


def build_ai_gateway_openai_client(
    api_key: str,
    ai_product: str,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
) -> OpenAI:
    """Go ai-gateway client on the caller's own bearer (``pha_``, ``phe_``)."""
    url = settings.AI_GATEWAY_URL
    if not url:
        raise GatewayNotConfiguredError("AI_GATEWAY_URL is not set")
    if not urlparse(url).path.rstrip("/").endswith("/v1"):
        raise GatewayNotConfiguredError(f"AI_GATEWAY_URL must end with /v1, got {url}")
    if not api_key:
        raise GatewayNotConfiguredError("api_key is required")
    return OpenAI(
        api_key=api_key,
        base_url=url,
        default_headers=ai_gateway_headers(
            ai_product=ai_product,
            trace_id=trace_id,
            session_id=session_id,
            properties=properties,
            distinct_id=distinct_id,
        ),
        http_client=httpx.Client(trust_env=False),
    )


def build_async_anthropic_client(
    ai_product: str | None = None,
    ai_stage: str | None = None,
    team_id: int | None = None,
    trace_id: str | None = None,
    properties: Mapping[str, str] | None = None,
) -> AsyncAnthropic:
    """Return a raw Anthropic client routed through the internal Go ai-gateway.

    ``ai_product`` rides on both ``X-PostHog-Product`` and the ``X-PostHog-Properties`` JSON blob;
    ``ai_stage`` and ``team_id`` ride on the blob only.
    ``team_id`` is the customer team the generation is attributed to (the usage report reads it as
    a property); it does not change the event's owning project, which the gateway derives from the
    ``phs_`` bearer. The Anthropic SDK appends ``/v1/messages``, so the client gets the gateway
    root rather than the ``/v1`` OpenAI base. The gateway fails over to Bedrock on its own.

    An attributed call also carries ``X-PostHog-Trace-Id``. Callers can supply a per-operation
    ``trace_id`` and custom ``properties``; otherwise the trace falls back to :func:`team_trace_id`.
    Raises GatewayNotConfiguredError when the Go ai-gateway pair is unset or malformed.
    trust_env=False keeps the in-cluster call off the egress proxy.
    """
    gateway = _require_ai_gateway_config()
    labels = dict(properties or {})
    if ai_stage:
        labels["ai_stage"] = ai_stage
    if team_id is not None:
        labels["team_id"] = str(team_id)
    return AsyncAnthropic(
        api_key=gateway.api_key,
        base_url=anthropic_gateway_base_url(gateway.url),
        default_headers=ai_gateway_headers(
            ai_product=ai_product,
            trace_id=trace_id or team_trace_id(team_id),
            properties=labels,
        ),
        http_client=httpx.AsyncClient(trust_env=False),
    )


def _ai_gateway_anthropic_client(
    gateway: AIGatewayConfig,
    ai_product: str | None,
    trace_id: str | None,
    properties: Mapping[str, str] | None,
    distinct_id: str | None,
    team_id: int | None,
    privacy_mode: bool = False,
) -> Anthropic:
    labels = dict(properties or {})
    if team_id is not None:
        labels["team_id"] = str(team_id)
    return Anthropic(
        api_key=gateway.api_key,
        base_url=anthropic_gateway_base_url(gateway.url),
        default_headers=ai_gateway_headers(
            ai_product=ai_product,
            trace_id=trace_id or team_trace_id(team_id),
            properties=labels,
            distinct_id=distinct_id,
            privacy_mode=privacy_mode,
        ),
        http_client=httpx.Client(trust_env=False),
    )


def build_anthropic_client(
    ai_product: str | None = None,
    trace_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
    team_id: int | None = None,
    privacy_mode: bool = False,
) -> Anthropic:
    """Build a native Anthropic client on the Go ai-gateway for synchronous Django worker code.

    Raises GatewayNotConfiguredError when the Go ai-gateway pair is unset or malformed. ``privacy_mode`` keeps
    the request and response out of the generation the gateway captures. The Anthropic SDK appends
    ``/v1/messages``, so the client removes the OpenAI ``/v1`` suffix.
    """
    gateway = _require_ai_gateway_config()
    return _ai_gateway_anthropic_client(gateway, ai_product, trace_id, properties, distinct_id, team_id, privacy_mode)


class AIGatewayHostError(RuntimeError):
    """A gateway client was about to send its key to a host other than the gateway."""


def _origin(url: httpx.URL) -> str:
    # httpx lowercases the host and drops a scheme's default port, so equal origins compare equal.
    return f"{url.scheme}://{url.netloc.decode('ascii')}"


def build_gemini_client(
    ai_product: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    properties: Mapping[str, str] | None = None,
    distinct_id: str | None = None,
    privacy_mode: bool = False,
    timeout_ms: int | None = None,
) -> genai.Client | None:
    """Return a plain ``google.genai.Client`` routed through the Go ai-gateway, or None when the gateway is unset.

    It skips the posthoganalytics wrapper because the gateway captures the generation.
    """
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        return None
    headers = (
        ai_gateway_headers(
            ai_product=ai_product,
            trace_id=trace_id,
            session_id=session_id,
            properties=properties,
            distinct_id=distinct_id,
            privacy_mode=privacy_mode,
        )
        or {}
    )
    base_url = anthropic_gateway_base_url(gateway.url)
    # `files.upload` sends its chunks with none of the client's headers, so the transports carry them and the key.
    transport_headers = {**headers, "x-goog-api-key": gateway.api_key}
    # Chunks go to whatever URL the upload start returned, so pin every request to the gateway host.
    expected_origin = _origin(httpx.URL(base_url))

    def pin_to_gateway(request: httpx.Request) -> None:
        if (origin := _origin(request.url)) != expected_origin:
            raise AIGatewayHostError(f"request origin must be the AI gateway {expected_origin}, got {origin}")

    async def apin_to_gateway(request: httpx.Request) -> None:
        pin_to_gateway(request)

    return genai.Client(
        api_key=gateway.api_key,
        http_options=genai_types.HttpOptions(
            base_url=base_url,
            headers=headers,
            timeout=timeout_ms,
            client_args={
                "trust_env": False,
                "headers": transport_headers,
                "event_hooks": {"request": [pin_to_gateway]},
            },
            # The SDK uses aiohttp for async whenever it is installed, and that session always trusts
            # proxy env vars. An explicit httpx transport switches async to httpx, which honours trust_env.
            async_client_args={
                "trust_env": False,
                "transport": httpx.AsyncHTTPTransport(),
                "headers": transport_headers,
                "event_hooks": {"request": [apin_to_gateway]},
            },
        ),
    )
