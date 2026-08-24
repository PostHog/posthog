"""Firecrawl egress telemetry.

Every Firecrawl call funnels through these recorders so request volume lands on one metric set
whichever subsystem made the call, attributed by the ``source`` label. Firecrawl meters each
endpoint separately, so the gauges' ``resource`` is the endpoint the observed headers describe.
"""

from collections.abc import Mapping

import requests
from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    default_normalize_endpoint,
    register_egress_observability,
)

FIRECRAWL_DOMAIN = "firecrawl"

_metrics = EgressMetrics(
    request_counter=Counter(
        "firecrawl_api_requests",
        "Number of Firecrawl API requests made through the Firecrawl egress client.",
        labelnames=["account", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "firecrawl_api_rate_limit_remaining",
        "Most recently observed Firecrawl rate limit remaining count by endpoint.",
        labelnames=["account", "resource"],
    ),
    limit_gauge=Gauge(
        "firecrawl_api_rate_limit_limit",
        "Most recently observed Firecrawl rate limit by endpoint.",
        labelnames=["account", "resource"],
    ),
    reset_gauge=Gauge(
        "firecrawl_api_rate_limit_reset_timestamp_seconds",
        "Most recently observed Firecrawl rate limit reset timestamp by endpoint "
        "(unset: Firecrawl does not document the encoding of its reset header).",
        labelnames=["account", "resource"],
    ),
)


def _float_header(headers: Mapping[str, str] | None, name: str) -> float | None:
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_firecrawl_rate_limit(response: requests.Response) -> RateLimitSnapshot:
    """Read Firecrawl's rate-limit headers when the response carries them. ``reset_at`` is left unset
    because Firecrawl does not document whether its reset header is an epoch or a number of seconds,
    and a gauge that could be either is worse than an unset one."""
    headers = response.headers if isinstance(response.headers, Mapping) else None
    request = getattr(response, "request", None)
    url = getattr(request, "url", None)
    return RateLimitSnapshot(
        resource=default_normalize_endpoint(url if isinstance(url, str) else None),
        remaining=_float_header(headers, "X-RateLimit-Remaining"),
        limit=_float_header(headers, "X-RateLimit-Limit"),
    )


firecrawl_egress = EgressObservability(FIRECRAWL_DOMAIN, _metrics, _parse_firecrawl_rate_limit)
register_egress_observability(firecrawl_egress)


def record_firecrawl_api_response(
    response: requests.Response,
    *,
    source: str,
    method: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Record one Firecrawl API response. The scope is always the instance's single account,
    because Firecrawl meters per API key and each instance holds exactly one."""
    firecrawl_egress.record_response(response, source=source, scope="default", method=method, endpoint=endpoint)


def record_firecrawl_api_exception(
    *,
    source: str,
    method: str,
    endpoint: str | None = None,
    url: str | None = None,
) -> None:
    """Record a request that raised before a response (timeout, connection error)."""
    firecrawl_egress.record_exception(source=source, scope="default", method=method, endpoint=endpoint, url=url)
