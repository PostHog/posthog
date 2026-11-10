"""Perplexity egress telemetry.

Every Perplexity call records through ``perplexity_egress``, attributed by the ``source`` label.

Perplexity documents ``x-ratelimit-limit``, ``x-ratelimit-remaining`` and ``x-ratelimit-reset``
(Unix seconds) on successful Agent API responses, for the organization's request limit. A 429
carries ``Retry-After`` instead and none of these, so the parser reads only those three names.
"""

from collections.abc import Mapping

from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    float_header,
)

# The headers describe the Agent API request limit, which Perplexity shares across all models and
# keys in the organization, so every observation describes the same one resource.
_RATE_LIMIT_RESOURCE = "agent_requests"

_metrics = EgressMetrics(
    request_counter=Counter(
        "perplexity_api_requests",
        "Number of Perplexity API requests made through the Perplexity egress client.",
        labelnames=["account", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "perplexity_api_rate_limit_remaining",
        "Most recently observed Perplexity Agent API request limit remaining count.",
        labelnames=["account", "resource"],
    ),
    limit_gauge=Gauge(
        "perplexity_api_rate_limit_limit",
        "Most recently observed Perplexity Agent API request limit.",
        labelnames=["account", "resource"],
    ),
    reset_gauge=Gauge(
        "perplexity_api_rate_limit_reset",
        "Most recently observed Perplexity Agent API request limit reset time, in Unix seconds.",
        labelnames=["account", "resource"],
    ),
)


def _parse_perplexity_rate_limit(headers: Mapping[str, str] | None, _url: str | None) -> RateLimitSnapshot:
    return RateLimitSnapshot(
        resource=_RATE_LIMIT_RESOURCE,
        remaining=float_header(headers, "x-ratelimit-remaining"),
        limit=float_header(headers, "x-ratelimit-limit"),
        reset_at=float_header(headers, "x-ratelimit-reset"),
    )


perplexity_egress = EgressObservability(_metrics, _parse_perplexity_rate_limit)
