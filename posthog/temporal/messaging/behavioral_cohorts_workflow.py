import asyncio
import datetime as dt
import dataclasses
from typing import Any, Optional

import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class BehavioralCohortsWorkflowInputs:
    """Inputs for the behavioral cohorts analysis workflow."""

    team_id: Optional[int] = None
    cohort_id: Optional[int] = None
    condition: Optional[str] = None
    min_matches: int = 3
    days: int = 30
    limit: Optional[int] = None
    parallelism: int = 10  # Number of parallel workers

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_id": self.cohort_id,
            "min_matches": self.min_matches,
            "days": self.days,
            "parallelism": self.parallelism,
        }


@dataclasses.dataclass
class ProcessConditionBatchInputs:
    """Inputs for processing a batch of conditions."""

    conditions: list[dict[str, Any]]
    min_matches: int
    days: int
    batch_number: int
    total_batches: int

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "batch_number": self.batch_number,
            "total_batches": self.total_batches,
            "conditions_count": len(self.conditions),
        }


@dataclasses.dataclass
class CohortMembershipResult:
    memberships: list[tuple[int, str, int]]
    conditions_processed: int
    batch_number: int


@temporalio.activity.defn
async def get_unique_conditions_activity(inputs: BehavioralCohortsWorkflowInputs) -> list[dict[str, Any]]:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    logger.info("Fetching unique conditions from ClickHouse")

    # Basic validation for reasonable bounds
    if not isinstance(inputs.days, int) or inputs.days < 0 or inputs.days > 365:
        raise ValueError(f"Invalid days value: {inputs.days}")
    if inputs.limit is not None and (not isinstance(inputs.limit, int) or inputs.limit < 1 or inputs.limit > 100000):
        raise ValueError(f"Invalid limit value: {inputs.limit}")

    where_clauses = ["date >= now() - toIntervalDay(%(days)s)"]
    params: dict[str, Any] = {"days": inputs.days}

    if inputs.team_id:
        where_clauses.append("team_id = %(team_id)s")
        params["team_id"] = inputs.team_id
    if inputs.cohort_id:
        where_clauses.append("cohort_id = %(cohort_id)s")
        params["cohort_id"] = inputs.cohort_id
    if inputs.condition:
        where_clauses.append("condition = %(condition)s")
        params["condition"] = inputs.condition

    where_clause = " AND ".join(where_clauses)

    # Use pagination to get all results in batches of 10,000
    all_conditions = []
    page_size = 10000
    offset = 0
    total_fetched = 0

    # If user specified a limit, respect it as the maximum total results
    user_limit = inputs.limit

    try:
        while True:
            # Calculate current batch limit
            if user_limit:
                remaining = user_limit - total_fetched
                if remaining <= 0:
                    break
                current_limit = min(page_size, remaining)
            else:
                current_limit = page_size

            query = """
                SELECT DISTINCT
                    team_id,
                    cohort_id,
                    condition
                FROM behavioral_cohorts_matches
                WHERE {where_clause}
                ORDER BY team_id, cohort_id, condition
                LIMIT {limit} OFFSET {offset}
            """.format(where_clause=where_clause, limit=current_limit, offset=offset)

            with tags_context(
                team_id=inputs.team_id,
                feature=Feature.BEHAVIORAL_COHORTS,
                cohort_id=inputs.cohort_id,
                product=Product.MESSAGING,
                query_type="get_unique_conditions",
            ):
                results = sync_execute(query, params, ch_user=ClickHouseUser.COHORTS, workload=Workload.OFFLINE)

            # If no results returned, we've reached the end
            if not results:
                break

            batch_conditions = [
                {
                    "team_id": row[0],
                    "cohort_id": row[1],
                    "condition": row[2],
                }
                for row in results
            ]

            all_conditions.extend(batch_conditions)
            total_fetched += len(batch_conditions)
            offset += current_limit

            logger.info(f"Fetched batch of {len(batch_conditions)} conditions (total: {total_fetched})")

            # If we got fewer results than requested, we've reached the end
            if len(results) < current_limit:
                break

        logger.info(f"Found {len(all_conditions)} unique conditions across all pages")
        return all_conditions

    except Exception as e:
        logger.exception("Error fetching unique conditions", error=str(e))
        raise


@temporalio.activity.defn
async def process_condition_batch_activity(inputs: ProcessConditionBatchInputs) -> CohortMembershipResult:
    """Process a batch of conditions to get cohort memberships."""
    logger = LOGGER.bind(batch_number=inputs.batch_number, total_batches=inputs.total_batches)

    logger.info(
        f"Processing batch {inputs.batch_number}/{inputs.total_batches} with {len(inputs.conditions)} conditions"
    )

    # Basic validation
    if not isinstance(inputs.days, int) or inputs.days < 0 or inputs.days > 365:
        raise ValueError(f"Invalid days value: {inputs.days}")
    if not isinstance(inputs.min_matches, int) or inputs.min_matches < 0:
        raise ValueError(f"Invalid min_matches value: {inputs.min_matches}")

    memberships = []

    async with Heartbeater():
        for idx, condition_data in enumerate(inputs.conditions, 1):
            team_id = condition_data["team_id"]
            cohort_id = condition_data["cohort_id"]
            condition_hash = condition_data["condition"]

            # Log progress within the batch
            if idx % 100 == 0 or idx == len(inputs.conditions):
                logger.info(
                    f"Batch {inputs.batch_number}: Processed {idx}/{len(inputs.conditions)} conditions",
                    batch_number=inputs.batch_number,
                    progress=idx,
                    total=len(inputs.conditions),
                )

            query = """
                SELECT
                    person_id
                FROM behavioral_cohorts_matches
                WHERE
                    team_id = %(team_id)s
                    AND cohort_id = %(cohort_id)s
                    AND condition = %(condition)s
                    AND date >= now() - toIntervalDay(%(days)s)
                    AND matches >= %(min_matches)s
                LIMIT 100000
            """

            try:
                with tags_context(
                    team_id=team_id,
                    feature=Feature.BEHAVIORAL_COHORTS,
                    cohort_id=cohort_id,
                    product=Product.MESSAGING,
                    query_type="get_cohort_memberships_batch",
                ):
                    results = sync_execute(
                        query,
                        {
                            "team_id": team_id,
                            "cohort_id": cohort_id,
                            "condition": condition_hash,
                            "days": inputs.days,
                            "min_matches": inputs.min_matches,
                        },
                        ch_user=ClickHouseUser.COHORTS,
                        workload=Workload.OFFLINE,
                    )

                for row in results:
                    person_id = row[0]
                    memberships.append((team_id, person_id, cohort_id))

            except Exception as e:
                logger.exception(
                    "Error processing condition in batch",
                    condition=condition_hash[:16] + "...",
                    error=str(e),
                    batch_number=inputs.batch_number,
                )
                continue

    logger.info(
        f"Batch {inputs.batch_number} completed: {len(memberships)} memberships from {len(inputs.conditions)} conditions",
        batch_number=inputs.batch_number,
        memberships_count=len(memberships),
        conditions_count=len(inputs.conditions),
    )

    return CohortMembershipResult(
        memberships=memberships, conditions_processed=len(inputs.conditions), batch_number=inputs.batch_number
    )


def split_into_batches(items: list[Any], batch_count: int) -> list[list[Any]]:
    """Split a list into approximately equal batches."""
    if batch_count <= 0:
        return [items]

    batch_size = max(1, len(items) // batch_count)
    remainder = len(items) % batch_count

    batches = []
    start = 0

    for i in range(batch_count):
        # Add 1 to batch size for the first 'remainder' batches to distribute items evenly
        current_batch_size = batch_size + (1 if i < remainder else 0)
        end = start + current_batch_size

        if start < len(items):  # Only create batch if there are items left
            batches.append(items[start:end])
            start = end

    return batches


@temporalio.workflow.defn(name="behavioral-cohorts-analysis")
class BehavioralCohortsWorkflow(PostHogWorkflow):
    """Temporal workflow for parallel behavioral cohorts analysis."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BehavioralCohortsWorkflowInputs:
        """Parse inputs from the management command CLI."""
        # For now, just return default inputs since this workflow
        # is called programmatically from the management command
        return BehavioralCohortsWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: BehavioralCohortsWorkflowInputs) -> dict[str, Any]:
        """Run the behavioral cohorts analysis workflow with fan-out pattern."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(f"Starting behavioral cohorts workflow with parallelism={inputs.parallelism}")

        # Step 1: Get all unique conditions
        conditions = await temporalio.workflow.execute_activity(
            get_unique_conditions_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        if not conditions:
            workflow_logger.warning("No conditions found matching the criteria")
            return {
                "total_memberships": 0,
                "conditions_processed": 0,
                "batches_processed": 0,
            }

        workflow_logger.info(f"Found {len(conditions)} conditions to process")

        # Step 2: Split conditions into batches based on parallelism setting
        # Ensure we don't create more batches than conditions
        actual_parallelism = min(inputs.parallelism, len(conditions))
        batches = split_into_batches(conditions, actual_parallelism)

        workflow_logger.info(f"Split into {len(batches)} batches for parallel processing")

        # Step 3: Process batches in parallel
        batch_tasks = []
        for batch_num, batch in enumerate(batches, 1):
            batch_inputs = ProcessConditionBatchInputs(
                conditions=batch,
                min_matches=inputs.min_matches,
                days=inputs.days,
                batch_number=batch_num,
                total_batches=len(batches),
            )

            # Create activity task with longer timeout for processing
            task = temporalio.workflow.execute_activity(
                process_condition_batch_activity,
                batch_inputs,
                start_to_close_timeout=dt.timedelta(minutes=30),  # Longer timeout for batch processing
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_interval=dt.timedelta(seconds=30),
                ),
            )
            batch_tasks.append(task)

        # Wait for all batches to complete
        results = await asyncio.gather(*batch_tasks)

        # Step 4: Aggregate results
        all_memberships = []
        total_conditions_processed = 0

        for result in results:
            all_memberships.extend(result.memberships)
            total_conditions_processed += result.conditions_processed
            workflow_logger.info(f"Batch {result.batch_number} contributed {len(result.memberships)} memberships")

        workflow_logger.info(
            f"Workflow completed: {len(all_memberships)} total memberships from {total_conditions_processed} conditions"
        )

        # Return summary statistics
        return {
            "total_memberships": len(all_memberships),
            "conditions_processed": total_conditions_processed,
            "batches_processed": len(batches),
            "memberships": all_memberships[:100],  # Return first 100 for display
        }
