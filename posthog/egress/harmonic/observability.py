"""Harmonic egress telemetry.

Every Harmonic call records through ``harmonic_egress``, attributed by the ``source`` label.

Harmonic's API reference documents ``X-Ratelimit-Limit-Second`` and ``X-Ratelimit-Remaining-Second``
on every response, so the parser reads only those. It documents no reset header, so this domain
declares no reset gauge. Production has recorded no value on either gauge yet; see the domain README.
"""

from collections.abc import Mapping

from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    float_header,
)

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
)


def _parse_harmonic_rate_limit(headers: Mapping[str, str] | None, _url: str | None) -> RateLimitSnapshot:
    return RateLimitSnapshot(
        resource=_RATE_LIMIT_RESOURCE,
        remaining=float_header(headers, "X-Ratelimit-Remaining-Second"),
        limit=float_header(headers, "X-Ratelimit-Limit-Second"),
    )


harmonic_egress = EgressObservability(_metrics, _parse_harmonic_rate_limit)
