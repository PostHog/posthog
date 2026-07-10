"""logo.dev egress telemetry.

Every logo.dev call funnels through these recorders so request volume lands on one metric set
whichever subsystem made the call (CDP icon picker, MCP store icons, ...), attributed by the
``source`` label. logo.dev reports no rate-limit response headers, so the parser returns an empty
snapshot and the gauges stay unset — they exist because :class:`EgressMetrics` requires the full
instrument set, and they start reporting the moment logo.dev grows the headers.
"""

from urllib.parse import urlparse

import requests
from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)

LOGODEV_DOMAIN = "logodev"

_metrics = EgressMetrics(
    request_counter=Counter(
        "logodev_api_requests",
        "Number of logo.dev API requests made through the logo.dev egress client.",
        labelnames=["account", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "logodev_api_rate_limit_remaining",
        "Most recently observed logo.dev rate limit remaining count (unset: logo.dev reports no rate-limit headers).",
        labelnames=["account", "resource"],
    ),
    limit_gauge=Gauge(
        "logodev_api_rate_limit_limit",
        "Most recently observed logo.dev rate limit (unset: logo.dev reports no rate-limit headers).",
        labelnames=["account", "resource"],
    ),
    reset_gauge=Gauge(
        "logodev_api_rate_limit_reset_timestamp_seconds",
        "Most recently observed logo.dev rate limit reset timestamp (unset: logo.dev reports no rate-limit headers).",
        labelnames=["account", "resource"],
    ),
)


def _parse_logodev_rate_limit(response: requests.Response) -> RateLimitSnapshot:
    return RateLimitSnapshot()


def _normalize_logodev_endpoint(url: str | None) -> str:
    """Collapse a logo.dev URL to a low-cardinality endpoint label. ``img.logo.dev/{brand-domain}``
    would otherwise mint one label per brand, so the brand path is templated to ``/img/{domain}``;
    the search API's fixed path is kept verbatim."""
    if not url:
        return "unknown"
    parsed = urlparse(url)
    if parsed.netloc == "img.logo.dev":
        return "/img/{domain}"
    path = parsed.path.rstrip("/")
    return path or "/"


logodev_egress = EgressObservability(
    LOGODEV_DOMAIN, _metrics, _parse_logodev_rate_limit, endpoint_normalizer=_normalize_logodev_endpoint
)
register_egress_observability(logodev_egress)


def record_logodev_api_response(
    response: requests.Response,
    *,
    source: str,
    method: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Record one logo.dev API response. The scope is always the instance's single account —
    logo.dev meters per token and each instance holds exactly one."""
    logodev_egress.record_response(response, source=source, scope="default", method=method, endpoint=endpoint)


def record_logodev_api_exception(
    *,
    source: str,
    method: str,
    endpoint: str | None = None,
    url: str | None = None,
) -> None:
    """Record a request that raised before a response (timeout, connection error)."""
    logodev_egress.record_exception(source=source, scope="default", method=method, endpoint=endpoint, url=url)
