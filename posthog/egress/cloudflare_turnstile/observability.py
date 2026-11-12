"""Cloudflare Turnstile siteverify outbound request telemetry.

Siteverify documents no rate-limit headers, so this domain declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

cloudflare_turnstile_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "cloudflare_turnstile_api_requests",
            "Outbound Cloudflare Turnstile siteverify requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
