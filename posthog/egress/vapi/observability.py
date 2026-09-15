"""Vapi outbound API request telemetry.

Vapi returns no rate-limit headers, so this domain declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

vapi_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "vapi_api_requests",
            "Outbound Vapi API requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
