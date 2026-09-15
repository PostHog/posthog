"""Prometheus metrics for inbound deliveries and the consumers they fan out to."""

from typing import Literal

from prometheus_client import Counter, Histogram

# outcome: what the transport answered, never what a consumer decided. `accepted` means the
# delivery was verified, parsed and handed to the dispatcher -- consumer failures are counted
# on their own metric below, because a failing consumer still gets a 2xx receipt.
DeliveryOutcome = Literal[
    "accepted",
    "method_not_allowed",
    "not_configured",
    "invalid_signature",
    "invalid_payload",
]

# budget_exceeded means the delivery ran out of wall clock before this consumer started. It is
# not marked in dedup, so the provider's redelivery reaches it.
ConsumerOutcome = Literal["succeeded", "failed", "deduped", "budget_exceeded"]

INGRESS_DELIVERIES_TOTAL = Counter(
    "posthog_ingress_deliveries_total",
    "Inbound webhook deliveries, labeled by provider app and what the transport answered",
    labelnames=["provider", "app", "outcome"],
)

INGRESS_CONSUMER_RUNS_TOTAL = Counter(
    "posthog_ingress_consumer_runs_total",
    "Consumer runs for inbound webhook deliveries, labeled by consumer and outcome",
    labelnames=["provider", "consumer", "outcome"],
)

INGRESS_CONSUMER_DURATION_SECONDS = Histogram(
    "posthog_ingress_consumer_duration_seconds",
    "Wall-clock seconds one consumer spent on one inbound webhook delivery",
    labelnames=["provider", "consumer"],
)


def observe_delivery(*, provider: str, app: str, outcome: DeliveryOutcome) -> None:
    INGRESS_DELIVERIES_TOTAL.labels(provider=provider, app=app, outcome=outcome).inc()


def observe_consumer_run(*, provider: str, consumer: str, outcome: ConsumerOutcome) -> None:
    INGRESS_CONSUMER_RUNS_TOTAL.labels(provider=provider, consumer=consumer, outcome=outcome).inc()


def observe_consumer_duration(*, provider: str, consumer: str, seconds: float) -> None:
    INGRESS_CONSUMER_DURATION_SECONDS.labels(provider=provider, consumer=consumer).observe(seconds)
