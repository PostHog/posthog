"""Browserless outbound request telemetry.

Browserless returns no rate-limit headers. Its `X-Response-*` headers describe the page it
fetched, not the API's own budget, so there is nothing to read a remaining count or a reset time
out of, and this domain declares no rate-limit gauges. Volume, status, and latency are what it can
honestly report. Verified against the hosted fleet, which returns a bare 200 with no `X-RateLimit-*`
and no `Retry-After`.
"""

from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

BROWSERLESS_SESSIONS_IN_FLIGHT = Gauge(
    "browserless_sessions_in_flight",
    "Browserless sessions this process holds open right now.",
    labelnames=["scope", "client", "source"],
    multiprocess_mode="livesum",
)

browserless_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "browserless_requests",
            "Outbound Browserless requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
