"""Browserless outbound request telemetry.

Browserless returns no rate-limit headers. Its `X-Response-*` headers describe the page it
fetched, not the API's own budget, so there is nothing to read a remaining count or a reset time
out of, and this domain declares no gauges. Volume, status, and latency are what it can honestly
report. Verified against the hosted fleet, which returns a bare 200 with no `X-RateLimit-*` and
no `Retry-After`.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

browserless_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "browserless_requests",
            "Outbound Browserless requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
