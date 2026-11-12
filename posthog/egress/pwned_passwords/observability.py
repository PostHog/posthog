"""Have I Been Pwned Pwned Passwords outbound request telemetry.

The API documents no rate-limit headers, so this domain declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

pwned_passwords_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "pwned_passwords_api_requests",
            "Outbound Have I Been Pwned Pwned Passwords range requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
