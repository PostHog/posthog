"""
Helper functions for triggering person property precalculation workflows.

Called when a realtime cohort with person property filters is created or updated.
"""

from django.conf import settings

from posthog.models.cohort.cohort import Cohort, CohortType
from posthog.temporal.messaging.precalculate_person_properties_workflow_coordinator import (
    PersonPropertyFilter,
    PrecalculatePersonPropertiesCoordinatorWorkflowInputs,
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


async def trigger_person_property_backfill(
    cohort: Cohort,
    parallelism: int = 5,
    batch_size: int = 1000,
    workflows_per_batch: int = 10,
    batch_delay_minutes: int = 1,
) -> str:
    """
    Trigger a Temporal workflow to backfill precalculated_person_properties for a cohort.

    Args:
        cohort: The cohort to backfill
        parallelism: Number of parallel child workflows to spawn
        batch_size: Number of persons to process per batch within each worker
        workflows_per_batch: Number of workflows to start per batch
        batch_delay_minutes: Delay between batches in minutes

    Returns:
        The workflow ID

    Raises:
        ValueError: If cohort has no person property filters or is not a realtime cohort
    """
    import structlog
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from posthog.temporal.common.client import async_connect

    logger = structlog.get_logger(__name__)

    if cohort.cohort_type != CohortType.REALTIME:
        raise ValueError(f"Cohort {cohort.id} is not a realtime cohort")

    filters = extract_person_property_filters(cohort)
    if not filters:
        raise ValueError(f"Cohort {cohort.id} has no person property filters with conditionHash and bytecode")

    client = await async_connect()

    workflow_id = f"precalculate-person-properties-{cohort.id}-{cohort.team_id}"

    inputs = PrecalculatePersonPropertiesCoordinatorWorkflowInputs(
        team_id=cohort.team_id,
        cohort_id=cohort.id,
        filters=filters,
        parallelism=parallelism,
        batch_size=batch_size,
        workflows_per_batch=workflows_per_batch,
        batch_delay_minutes=batch_delay_minutes,
    )

    try:
        await client.start_workflow(
            "precalculate-person-properties-coordinator",
            inputs,
            id=workflow_id,
            task_queue=settings.MESSAGING_TASK_QUEUE,
        )
        logger.info(
            f"Started new backfill workflow for cohort {cohort.id}",
            cohort_id=cohort.id,
            workflow_id=workflow_id,
            filter_count=len(filters),
        )
    except WorkflowAlreadyStartedError:
        logger.info(
            f"Backfill workflow already running for cohort {cohort.id}, skipping",
            cohort_id=cohort.id,
            workflow_id=workflow_id,
            filter_count=len(filters),
        )

    return workflow_id
