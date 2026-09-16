"""Harmonic egress telemetry.

Every Harmonic call records through ``harmonic_egress``, attributed by the ``source`` label.

Harmonic's API reference documents ``X-Ratelimit-Limit-Second`` and ``X-Ratelimit-Remaining-Second``
on every response, so the parser reads only those. It documents no reset header, so this domain
declares no reset gauge. Production has recorded no value on either gauge yet; see the domain README.
"""

from collections.abc import Mapping

from prometheus_client import Counter, Gauge, Histogram

from posthog.egress.limiter.policies import Priority
from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    float_header,
)

# Harmonic rate-limits the whole account rather than per endpoint, so every observed header
# describes the same one resource.
_RATE_LIMIT_RESOURCE = "account"
_METRIC_SOURCES = frozenset(
    {"harmonic_client", "salesforce_enrichment_bulk", "salesforce_enrichment_debug", "growth_enrichment_provider"}
)
_METRIC_ENDPOINTS = frozenset({"/graphql", "/companies/{id}", "/enrichment_status"})

_request_duration = Histogram(
    "harmonic_api_request_duration_seconds",
    "Time spent waiting for a Harmonic HTTP response, excluding local rate-limit admission waits.",
    labelnames=["source", "priority", "endpoint", "outcome"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60),
)
_admission_wait = Histogram(
    "harmonic_api_admission_wait_seconds",
    "Time a Harmonic caller waits before attempting a rate-limited request.",
    labelnames=["source", "priority"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

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


def _metric_source(source: str) -> str:
    return source if source in _METRIC_SOURCES else "other"


def record_harmonic_request_duration(
    seconds: float, *, source: str, priority: Priority, endpoint: str | None, outcome: str
) -> None:
    endpoint_label = endpoint if endpoint in _METRIC_ENDPOINTS else "other"
    outcome_label = "response" if outcome == "response" else "exception"
    _request_duration.labels(_metric_source(source), priority.value, endpoint_label, outcome_label).observe(seconds)


def record_harmonic_admission_wait(seconds: float, *, source: str, priority: Priority) -> None:
    _admission_wait.labels(_metric_source(source), priority.value).observe(seconds)
