"""OpenAI auth (ChatGPT OAuth) outbound request telemetry.

The token endpoint documents no rate-limit headers, so this domain declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

openai_auth_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "openai_auth_api_requests",
            "Outbound OpenAI auth (ChatGPT OAuth token and revoke) requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
