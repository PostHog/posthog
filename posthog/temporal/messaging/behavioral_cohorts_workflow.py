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
    offset: Optional[int] = None  # Starting offset for this workflow's range
    conditions_page_size: int = 1000  # Max conditions to return per activity call (configurable for testing)

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_id": self.cohort_id,
            "min_matches": self.min_matches,
            "days": self.days,
            "conditions_page_size": self.conditions_page_size,
            "offset": self.offset,
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
    memberships_count: int  # Just the count, not the actual data
    conditions_processed: int
    batch_number: int


@dataclasses.dataclass
class GetConditionsPageInputs:
    """Inputs for fetching a page of conditions."""

    team_id: Optional[int] = None
    cohort_id: Optional[int] = None
    condition: Optional[str] = None
    days: int = 30
    limit: Optional[int] = None
    offset: int = 0
    page_size: int = 10000


@dataclasses.dataclass
class ConditionsPageResult:
    """Result from fetching a page of conditions."""

    conditions: list[dict[str, Any]]
    has_more: bool
    total_fetched: int


@temporalio.activity.defn
async def get_unique_conditions_page_activity(inputs: GetConditionsPageInputs) -> ConditionsPageResult:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    logger.info(
        f"Fetching unique conditions page from ClickHouse (offset={inputs.offset}, page_size={inputs.page_size})"
    )

    # Send heartbeat at start
    temporalio.activity.heartbeat()

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

    # Calculate effective limit for this page
    if inputs.limit:
        current_limit = inputs.limit
    else:
        current_limit = inputs.page_size

    try:
        query = """
            SELECT DISTINCT
                team_id,
                cohort_id,
                condition
            FROM behavioral_cohorts_matches
            WHERE {where_clause}
            ORDER BY team_id, cohort_id, condition
            LIMIT {limit} OFFSET {offset}
        """.format(where_clause=where_clause, limit=current_limit, offset=inputs.offset)

        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            cohort_id=inputs.cohort_id,
            product=Product.MESSAGING,
            query_type="get_unique_conditions_page",
        ):
            results = sync_execute(query, params, ch_user=ClickHouseUser.COHORTS, workload=Workload.OFFLINE)

        conditions = [
            {
                "team_id": row[0],
                "cohort_id": row[1],
                "condition": row[2],
            }
            for row in results
        ]

        # Check if there are more results
        has_more = len(results) == current_limit
        total_fetched = inputs.offset + len(conditions)

        logger.info(
            f"Fetched page with {len(conditions)} conditions (offset={inputs.offset}, total={total_fetched}, has_more={has_more})"
        )

        return ConditionsPageResult(conditions=conditions, has_more=has_more, total_fetched=total_fetched)

    except Exception as e:
        logger.exception("Error fetching unique conditions page", error=str(e))
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

    memberships_count = 0

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
                FROM (
                    SELECT
                        person_id,
                        SUM(matches) as total_matches
                    FROM behavioral_cohorts_matches
                    WHERE
                        team_id = %(team_id)s
                        AND cohort_id = %(cohort_id)s
                        AND condition = %(condition)s
                        AND date >= now() - toIntervalDay(%(days)s)
                    GROUP BY person_id
                    HAVING total_matches >= %(min_matches)s
                )
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

                # Just count the memberships, don't store them
                memberships_count += len(results)

            except Exception as e:
                logger.exception(
                    "Error processing condition in batch",
                    condition=condition_hash[:16] + "...",
                    error=str(e),
                    batch_number=inputs.batch_number,
                )
                continue

    logger.info(
        f"Batch {inputs.batch_number} completed: {memberships_count} memberships from {len(inputs.conditions)} conditions",
        batch_number=inputs.batch_number,
        memberships_count=memberships_count,
        conditions_count=len(inputs.conditions),
    )

    return CohortMembershipResult(
        memberships_count=memberships_count,
        conditions_processed=len(inputs.conditions),
        batch_number=inputs.batch_number,
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
        workflow_logger.info(f"Starting behavioral cohorts child workflow for range starting at offset={inputs.offset}")

        # Use provided offset if this is a child workflow
        offset = inputs.offset or 0

        # Step 1: Fetch all conditions for this workflow's range in one go
        conditions_limit = inputs.limit  # This workflow's assigned range
        workflow_logger.info(f"Fetching conditions starting at offset={offset}, limit={conditions_limit}")

        # Fetch all conditions for this child workflow at once
        page_inputs = GetConditionsPageInputs(
            team_id=inputs.team_id,
            cohort_id=inputs.cohort_id,
            condition=inputs.condition,
            days=inputs.days,
            limit=conditions_limit,
            offset=offset,
            page_size=conditions_limit or 10000,  # Fetch all at once
        )

        page_result = await temporalio.workflow.execute_activity(
            get_unique_conditions_page_activity,
            page_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            heartbeat_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        all_conditions: list[dict[str, Any]] = page_result.conditions
        workflow_logger.info(f"Fetched {len(all_conditions)} conditions for this child workflow")

        if not all_conditions:
            workflow_logger.warning("No conditions found for this workflow's range")
            return {
                "total_memberships": 0,
                "conditions_processed": 0,
                "batches_processed": 0,
            }

        workflow_logger.info(f"Processing {len(all_conditions)} conditions sequentially")

        # Step 2: Process all conditions in a single activity (no internal parallelism needed)
        workflow_logger.info(f"Processing {len(all_conditions)} conditions sequentially")

        batch_inputs = ProcessConditionBatchInputs(
            conditions=all_conditions,
            min_matches=inputs.min_matches,
            days=inputs.days,
            batch_number=1,
            total_batches=1,
        )

        result = await temporalio.workflow.execute_activity(
            process_condition_batch_activity,
            batch_inputs,
            start_to_close_timeout=dt.timedelta(minutes=30),
            heartbeat_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(seconds=30),
            ),
        )

        workflow_logger.info(
            f"Child workflow completed: {result.memberships_count} memberships from {result.conditions_processed} conditions"
        )

        # Return summary statistics
        return {
            "total_memberships": result.memberships_count,
            "conditions_processed": result.conditions_processed,
            "batches_processed": 1,
        }
