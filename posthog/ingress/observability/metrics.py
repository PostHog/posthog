"""Prometheus metrics for inbound deliveries and the consumers they fan out to."""

from typing import Literal

from prometheus_client import Counter, Histogram

# outcome: what the transport answered, never what a consumer returned. `accepted` means the
# delivery was verified, parsed and taken by every consumer it was handed to. `retry_requested`
# means it was not, on a provider that redelivers on a non-2xx; on a provider that does not, the
# same delivery is still `accepted` and only the consumer metric below records the failure.
DeliveryOutcome = Literal[
    "accepted",
    "method_not_allowed",
    "throttled",
    "not_configured",
    "invalid_signature",
    "invalid_payload",
    "forward_failed",
    "retry_requested",
]

# budget_exceeded means the delivery ran out of wall clock before this consumer started. It is
# not marked in dedup, so the provider's redelivery reaches it.
ConsumerOutcome = Literal["succeeded", "failed", "deduped", "budget_exceeded"]

# What a consumer answered when asked which region owns the delivery's resource; `failed` is the
# lookup raising, which counts as undecided.
OwnershipOutcome = Literal["local", "elsewhere", "undecided", "failed"]

# What the owning region answered the replayed request: `rejected` is a non-2xx, `failed` is the
# request never completing.
ForwardOutcome = Literal["forwarded", "rejected", "failed"]

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

INGRESS_OWNERSHIP_TOTAL = Counter(
    "posthog_ingress_ownership_total",
    "Ownership answers from consumers that declare one, labeled by consumer and answer",
    labelnames=["provider", "consumer", "outcome"],
)

INGRESS_FORWARDS_TOTAL = Counter(
    "posthog_ingress_forwards_total",
    "Requests replayed to the region that owns the delivery, labeled by what that region answered",
    labelnames=["provider", "app", "outcome"],
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


def observe_ownership(*, provider: str, consumer: str, outcome: OwnershipOutcome) -> None:
    INGRESS_OWNERSHIP_TOTAL.labels(provider=provider, consumer=consumer, outcome=outcome).inc()


def observe_forward(*, provider: str, app: str, outcome: ForwardOutcome) -> None:
    INGRESS_FORWARDS_TOTAL.labels(provider=provider, app=app, outcome=outcome).inc()


def observe_consumer_duration(*, provider: str, consumer: str, seconds: float) -> None:
    INGRESS_CONSUMER_DURATION_SECONDS.labels(provider=provider, consumer=consumer).observe(seconds)
