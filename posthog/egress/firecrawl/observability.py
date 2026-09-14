"""Firecrawl egress telemetry.

Every Firecrawl call records through ``firecrawl_egress``, so request volume lands on one metric set
whichever subsystem made the call, attributed by the ``source`` label. Firecrawl meters each
endpoint separately, so the gauges' ``resource`` is the endpoint the observed headers describe.
"""

from collections.abc import Mapping

from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    default_normalize_endpoint,
    float_header,
)

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
)


def _parse_firecrawl_rate_limit(headers: Mapping[str, str] | None, url: str | None) -> RateLimitSnapshot:
    """Read Firecrawl's rate-limit headers when the response carries them. ``reset_at`` is left unset
    because Firecrawl does not document whether its reset header is an epoch or a number of seconds,
    and a gauge that could be either is worse than an unset one. ``resource`` comes from the request
    url, not a curated endpoint label, because Firecrawl meters each endpoint separately."""
    return RateLimitSnapshot(
        resource=default_normalize_endpoint(url),
        remaining=float_header(headers, "X-RateLimit-Remaining"),
        limit=float_header(headers, "X-RateLimit-Limit"),
    )


firecrawl_egress = EgressObservability(_metrics, _parse_firecrawl_rate_limit)
