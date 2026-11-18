"""Google Workspace outbound request telemetry.

Google reports quota exhaustion in the error body, not in rate-limit headers, so this domain
declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

google_workspace_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "google_workspace_api_requests",
            "Outbound Google Workspace API requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
