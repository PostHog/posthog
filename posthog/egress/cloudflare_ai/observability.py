from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

cloudflare_ai_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "cloudflare_ai_api_requests",
            "Outbound Cloudflare AI API requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
