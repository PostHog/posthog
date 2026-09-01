"""Harmonic egress telemetry.

Every Harmonic call funnels through these recorders so request volume lands on one metric set,
attributed by the ``source`` label. Harmonic's client is aiohttp-based
(``ee/billing/salesforce_enrichment/harmonic_client.py``), so its responses are
``aiohttp.ClientResponse`` (``.status``), not ``requests.Response`` (``.status_code``) — the shape
``EgressObservability.record_response`` is typed against. This module records directly instead,
reusing only the transport-agnostic ``EgressMetrics``/``RateLimitSnapshot`` dataclasses.

Harmonic's own rate-limit header names are not confirmed from public docs (their docs page is a
client-rendered SPA). The parser below reads the GitHub-style ``X-RateLimit-*`` names plus the
``X-Ratelimit-*-Second`` variants, and returns None for anything absent or unparseable rather than
raising — telemetry must never break the request it is recording.
"""

from collections.abc import Mapping

from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import EgressMetrics, RateLimitSnapshot

HARMONIC_DOMAIN = "harmonic"

# Harmonic bills one account-wide limit, not a per-installation one, so every call shares this scope.
_SCOPE = "default"

# Harmonic rate-limits the whole account rather than per endpoint, so every observed header
# describes the same one resource.
_RATE_LIMIT_RESOURCE = "account"

_metrics = EgressMetrics(
    request_counter=Counter(
        "harmonic_api_requests",
        "Number of Harmonic API requests made through the Harmonic egress client.",
        labelnames=["scope", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "harmonic_api_rate_limit_remaining",
        "Most recently observed Harmonic rate limit remaining count.",
        labelnames=["scope", "resource"],
    ),
    limit_gauge=Gauge(
        "harmonic_api_rate_limit_limit",
        "Most recently observed Harmonic rate limit.",
        labelnames=["scope", "resource"],
    ),
    reset_gauge=Gauge(
        "harmonic_api_rate_limit_reset_timestamp_seconds",
        "Most recently observed Harmonic rate limit reset timestamp.",
        labelnames=["scope", "resource"],
    ),
)

# Preferred first: the per-second variant matches the window this domain's policy actually gates
# Falls back to the GitHub-style name in case Harmonic serves only that one.
_REMAINING_HEADERS = ("X-Ratelimit-Remaining-Second", "X-RateLimit-Remaining")
_LIMIT_HEADERS = ("X-Ratelimit-Limit-Second", "X-RateLimit-Limit")
_RESET_HEADERS = ("X-RateLimit-Reset",)


def _first_float_header(headers: Mapping[str, str], names: tuple[str, ...]) -> float | None:
    for name in names:
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _parse_harmonic_rate_limit(headers: Mapping[str, str] | None) -> RateLimitSnapshot:
    headers = headers or {}
    return RateLimitSnapshot(
        resource=_RATE_LIMIT_RESOURCE,
        remaining=_first_float_header(headers, _REMAINING_HEADERS),
        limit=_first_float_header(headers, _LIMIT_HEADERS),
        reset_at=_first_float_header(headers, _RESET_HEADERS),
    )


def record_harmonic_api_response(
    status: int,
    headers: Mapping[str, str] | None,
    *,
    source: str,
    method: str,
    endpoint: str | None = None,
) -> None:
    """Record one Harmonic API response. ``method``/``endpoint`` are the caller's curated labels —
    Harmonic's few endpoints (``/graphql``, ``/companies/{id}``, ``/enrichment_status``) are cheap
    to pass explicitly, so there is no URL-derived endpoint normaliser here."""
    endpoint_label = endpoint or "unknown"
    _metrics.request_counter.labels(_SCOPE, method.upper(), endpoint_label, str(status), source).inc()

    snapshot = _parse_harmonic_rate_limit(headers)
    if snapshot.remaining is not None:
        _metrics.remaining_gauge.labels(_SCOPE, snapshot.resource).set(snapshot.remaining)
    if snapshot.limit is not None:
        _metrics.limit_gauge.labels(_SCOPE, snapshot.resource).set(snapshot.limit)
    if snapshot.reset_at is not None:
        _metrics.reset_gauge.labels(_SCOPE, snapshot.resource).set(snapshot.reset_at)


def record_harmonic_api_exception(*, source: str, method: str, endpoint: str | None = None) -> None:
    """Record a request that raised before a response (timeout, connection error)."""
    endpoint_label = endpoint or "unknown"
    _metrics.request_counter.labels(_SCOPE, method.upper(), endpoint_label, "exception", source).inc()
