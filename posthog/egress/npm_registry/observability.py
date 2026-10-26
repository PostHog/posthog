"""npm registry outbound request telemetry.

The registry documents no rate-limit headers, so this domain declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

npm_registry_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "npm_registry_api_requests",
            "Outbound public npm registry metadata requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
