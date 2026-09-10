from collections.abc import Callable
from typing import Literal

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram

from posthog.temporal.common.logger import get_write_only_logger

PayloadKind = Literal["discovery", "hydrated", "activation"]
AdmissionOutcome = Literal["reserved", "already_claimed", "deferred_capacity"]
ClaimTransition = Literal["confirmed", "renewed", "completed", "released", "quarantined"]

_PAYLOAD_KINDS = {"discovery", "hydrated", "activation"}
_ADMISSION_OUTCOMES = {"reserved", "already_claimed", "deferred_capacity"}
_CLAIM_TRANSITIONS = {"confirmed", "renewed", "completed", "released", "quarantined"}

LOGGER = get_write_only_logger(__name__)


class SchedulerMetrics:
    def __init__(self, *, registry: CollectorRegistry = REGISTRY):
        self._payload_bytes = Histogram(
            "posthog_temporal_scheduler_payload_bytes",
            "Encoded Temporal scheduler payload size in bytes.",
            ["scheduler", "region", "payload_kind"],
            buckets=(1_024, 4_096, 16_384, 65_536, 262_144, 524_288),
            registry=registry,
        )
        self._admission = Counter(
            "posthog_temporal_scheduler_admission",
            "Scheduler items handled by each admission outcome.",
            ["scheduler", "region", "outcome"],
            registry=registry,
        )
        self._claim_transitions = Counter(
            "posthog_temporal_scheduler_claim_transition",
            "Durable scheduler claim lifecycle transitions.",
            ["scheduler", "region", "transition"],
            registry=registry,
        )
        self._permits_in_flight = Gauge(
            "posthog_temporal_scheduler_permits_in_flight",
            "Globally admitted scheduler items that have not reached a terminal claim state.",
            ["scheduler", "region"],
            registry=registry,
        )

    @staticmethod
    def _validate_scope(scheduler: str, region: str) -> None:
        if not scheduler or not region:
            raise ValueError("scheduler and region metric labels must not be empty")

    def observe_payload(
        self,
        scheduler: str,
        region: str,
        payload_kind: PayloadKind,
        size_bytes: int,
    ) -> None:
        self._validate_scope(scheduler, region)
        if payload_kind not in _PAYLOAD_KINDS:
            raise ValueError(f"unsupported payload_kind: {payload_kind}")
        if size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        self._payload_bytes.labels(scheduler=scheduler, region=region, payload_kind=payload_kind).observe(size_bytes)

    def record_admission(
        self,
        scheduler: str,
        region: str,
        outcome: AdmissionOutcome,
        count: int = 1,
    ) -> None:
        self._validate_scope(scheduler, region)
        if outcome not in _ADMISSION_OUTCOMES:
            raise ValueError(f"unsupported admission outcome: {outcome}")
        if count < 0:
            raise ValueError("count must not be negative")
        self._admission.labels(scheduler=scheduler, region=region, outcome=outcome).inc(count)

    def record_claim_transition(
        self,
        scheduler: str,
        region: str,
        transition: ClaimTransition,
    ) -> None:
        self._validate_scope(scheduler, region)
        if transition not in _CLAIM_TRANSITIONS:
            raise ValueError(f"unsupported claim transition: {transition}")
        self._claim_transitions.labels(scheduler=scheduler, region=region, transition=transition).inc()

    def set_permits_in_flight(self, scheduler: str, region: str, count: int) -> None:
        self._validate_scope(scheduler, region)
        if count < 0:
            raise ValueError("permit count must not be negative")
        self._permits_in_flight.labels(scheduler=scheduler, region=region).set(count)


DEFAULT_SCHEDULER_METRICS = SchedulerMetrics()


def record_scheduler_metrics_safely(operation: Callable[[], None]) -> None:
    try:
        operation()
    except Exception:
        LOGGER.exception("temporal_scheduler.metric_recording_failed")
