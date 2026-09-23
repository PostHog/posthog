from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

typesafe_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "typesafe_api_requests",
            "Number of TypeSafe API requests made through the TypeSafe egress client.",
            labelnames=["account", "method", "endpoint", "status_code", "source"],
        ),
    )
)
