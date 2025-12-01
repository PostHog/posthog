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
    Extract person property filters from a cohort that have conditionHash and bytecode.

    Returns a list of PersonPropertyFilter objects suitable for passing to the workflow.
    """
    filters = []

    for group in cohort.filters.get("properties", {}).get("values", []):
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


def should_trigger_backfill(cohort: Cohort, is_new: bool, old_filters: dict | None = None) -> bool:
    """
    Determine if we should trigger a backfill for this cohort.

    Args:
        cohort: The cohort being saved
        is_new: True if this is a new cohort
        old_filters: The previous filters if this is an update

    Returns:
        True if backfill should be triggered
    """
    import structlog

    logger = structlog.get_logger(__name__)

    # Only trigger for realtime cohorts
    if cohort.cohort_type != CohortType.REALTIME:
        logger.info(
            f"Not triggering backfill: cohort {cohort.id} is not realtime",
            cohort_id=cohort.id,
            cohort_type=cohort.cohort_type,
        )
        return False

    # Check if cohort has person property filters
    filters = extract_person_property_filters(cohort)
    if not filters:
        logger.info(
            f"Not triggering backfill: cohort {cohort.id} has no person property filters",
            cohort_id=cohort.id,
        )
        return False

    # Always trigger for new cohorts
    if is_new:
        logger.info(
            f"Triggering backfill: new cohort {cohort.id} with {len(filters)} person property filters",
            cohort_id=cohort.id,
            filter_count=len(filters),
        )
        return True

    # For updates, check if person property filters changed
    if old_filters is None:
        # Can't determine if changed, trigger to be safe
        logger.info(
            f"Triggering backfill: cohort {cohort.id} has no old_filters to compare",
            cohort_id=cohort.id,
        )
        return True

    # Extract old filters and compare
    old_cohort_obj = Cohort(filters=old_filters)
    old_filter_hashes = {f.condition_hash for f in extract_person_property_filters(old_cohort_obj)}
    new_filter_hashes = {f.condition_hash for f in filters}

    logger.info(
        f"Comparing filters for cohort {cohort.id}",
        cohort_id=cohort.id,
        old_filter_hashes=old_filter_hashes,
        new_filter_hashes=new_filter_hashes,
    )

    # Trigger if filters changed
    changed = old_filter_hashes != new_filter_hashes
    if changed:
        logger.info(
            f"Triggering backfill: person property filters changed for cohort {cohort.id}",
            cohort_id=cohort.id,
        )
    else:
        logger.info(
            f"Not triggering backfill: person property filters unchanged for cohort {cohort.id}",
            cohort_id=cohort.id,
        )
    return changed
