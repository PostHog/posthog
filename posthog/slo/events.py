import os

import posthoganalytics

from posthog.slo.types import SloCompletedProperties, SloStartedProperties


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
