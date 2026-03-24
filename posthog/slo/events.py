import os

import posthoganalytics
from prometheus_client import Counter, Histogram

from posthog.slo.types import SloCompletedProperties, SloStartedProperties

OPERATION_STARTED_COUNTER = Counter(
    "slo_operation_started",
    "A counter keeping track of when a slo-measured operation has started.",
    labelnames=["area", "operation"],
)
OPERATION_COMPLETED_COUNTER = Counter(
    "slo_operation_completed",
    "A counter keeping track of when a slo-measured operation has completed.",
    labelnames=["area", "operation", "outcome"],
)
OPERATION_DURATION = Histogram(
    "slo_operation_duration_seconds",
    "Time spent for a slo-measured operation",
    labelnames=["area", "operation", "outcome"],
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
        30.0,
        60.0,
        120.0,
        300.0,
        600.0,
        1200.0,
        float("inf"),
    ),
)


def emit_slo_started(
    distinct_id: str,
    properties: SloStartedProperties,
    extra_properties: dict | None = None,
) -> None:
    all_properties = properties.to_dict()
    all_properties["deploy_sha"] = os.environ.get("COMMIT_SHA")
    if extra_properties:
        all_properties.update(extra_properties)

    posthoganalytics.capture(
        distinct_id=distinct_id,
        event="slo_operation_started",
        properties=all_properties,
    )
    OPERATION_STARTED_COUNTER.labels(
        area=properties.area,
        operation=properties.operation,
    ).inc()


def emit_slo_completed(
    distinct_id: str,
    properties: SloCompletedProperties,
    extra_properties: dict | None = None,
) -> None:
    all_properties = properties.to_dict()
    all_properties["deploy_sha"] = os.environ.get("COMMIT_SHA")
    if extra_properties:
        all_properties.update(extra_properties)

    posthoganalytics.capture(
        distinct_id=distinct_id,
        event="slo_operation_completed",
        properties=all_properties,
    )
    OPERATION_COMPLETED_COUNTER.labels(
        area=properties.area,
        operation=properties.operation,
        outcome=properties.outcome,
    ).inc()

    if properties.duration_ms is not None:
        OPERATION_DURATION.labels(
            area=properties.area,
            operation=properties.operation,
            outcome=properties.outcome,
        ).observe(properties.duration_ms / 1000)
