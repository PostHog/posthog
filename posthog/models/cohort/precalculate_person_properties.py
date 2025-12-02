"""
Helper functions for triggering precalculated person properties backfill workflows.

Called when a realtime cohort with person property filters is created or updated.
"""

from posthog.models.cohort.cohort import Cohort
from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    PersonPropertyFilter,
)


def extract_person_property_filters(cohort: Cohort) -> list[PersonPropertyFilter]:
    """
    Extract person property filters from a realtime cohort

    Returns a list of PersonPropertyFilter objects suitable for passing to the workflow.
    """
    filters: list[PersonPropertyFilter] = []

    if not cohort.filters:
        return filters

    properties = cohort.filters.get("properties")
    if not properties:
        return filters

    for group in properties.get("values", []):
        for prop in group.get("values", []):
            # Only process person property filters
            if prop.get("type") != "person":
                continue

            condition_hash = prop.get("conditionHash")
            bytecode = prop.get("bytecode")

            if not condition_hash or not bytecode:
                continue

            filters.append(
                PersonPropertyFilter(
                    condition_hash=condition_hash,
                    bytecode=bytecode,
                )
            )

    return filters
