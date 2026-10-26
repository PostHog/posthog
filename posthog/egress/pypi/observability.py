"""PyPI outbound request telemetry.

PyPI documents no rate-limit headers for its JSON or Integrity APIs, so this domain declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

pypi_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "pypi_api_requests",
            "Outbound PyPI JSON and Integrity API requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
