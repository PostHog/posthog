import math
import datetime as dt
import dataclasses
from typing import Any, Optional

import temporalio.common
import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.constants import MESSAGING_TASK_QUEUE
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CoordinatorWorkflowInputs:
    """Inputs for the coordinator workflow that spawns child workflows."""

    team_id: Optional[int] = None
    cohort_id: Optional[int] = None
    condition: Optional[str] = None
    min_matches: int = 3
    days: int = 30
    limit: Optional[int] = None
    parallelism: int = 10  # Number of child workflows to spawn
    conditions_per_workflow: int = 5000  # Max conditions per child workflow

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_id": self.cohort_id,
            "min_matches": self.min_matches,
            "days": self.days,
            "parallelism": self.parallelism,
            "conditions_per_workflow": self.conditions_per_workflow,
        }


@dataclasses.dataclass
class ConditionsCountResult:
    """Result from counting total conditions."""

    count: int


@temporalio.activity.defn
async def get_conditions_count_activity(inputs: CoordinatorWorkflowInputs) -> ConditionsCountResult:
    """Get the total count of unique conditions."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    logger.info("Counting total unique conditions")

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

    # Count query - much lighter than fetching all conditions
    query = f"""
        SELECT COUNT(DISTINCT (team_id, cohort_id, condition)) as count
        FROM behavioral_cohorts_matches
        WHERE {where_clause}
    """

    if inputs.limit:
        # Apply limit to the subquery
        query = f"""
            SELECT COUNT(*) as count FROM (
                SELECT DISTINCT team_id, cohort_id, condition
                FROM behavioral_cohorts_matches
                WHERE {where_clause}
                LIMIT {inputs.limit}
            )
        """

    try:
        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            cohort_id=inputs.cohort_id,
            product=Product.MESSAGING,
            query_type="count_unique_conditions",
        ):
            results = sync_execute(query, params, ch_user=ClickHouseUser.COHORTS, workload=Workload.OFFLINE)

        count = results[0][0] if results else 0
        logger.info(f"Found {count} total unique conditions")
        return ConditionsCountResult(count=count)

    except Exception as e:
        logger.exception("Error counting unique conditions", error=str(e))
        raise


@temporalio.workflow.defn(name="behavioral-cohorts-coordinator")
class BehavioralCohortsCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that spawns multiple child workflows for true parallelism."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CoordinatorWorkflowInputs:
        """Parse inputs from the management command CLI."""
        return CoordinatorWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: CoordinatorWorkflowInputs) -> None:
        """Run the coordinator workflow that spawns child workflows."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(f"Starting coordinator with parallelism={inputs.parallelism}")

        # Step 1: Get total count of conditions
        count_result = await temporalio.workflow.execute_activity(
            get_conditions_count_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        total_conditions = count_result.count
        if total_conditions == 0:
            workflow_logger.warning("No conditions found")
            return

        workflow_logger.info(f"Scheduling {total_conditions} conditions across {inputs.parallelism} child workflows")

        # Step 2: Calculate ranges for each child workflow
        conditions_per_workflow = math.ceil(total_conditions / inputs.parallelism)
        conditions_per_workflow = min(conditions_per_workflow, inputs.conditions_per_workflow)

        # Step 3: Import the child workflow inputs and workflow class
        from posthog.temporal.messaging.behavioral_cohorts_workflow import (
            BehavioralCohortsWorkflow,
            BehavioralCohortsWorkflowInputs,
        )

        # Step 4: Launch child workflows - fire and forget
        workflows_scheduled = 0
        for i in range(inputs.parallelism):
            offset = i * conditions_per_workflow
            limit = min(conditions_per_workflow, total_conditions - offset)

            if limit <= 0:
                break

            child_id = f"{temporalio.workflow.info().workflow_id}-child-{i}"
            child_inputs = BehavioralCohortsWorkflowInputs(
                team_id=inputs.team_id,
                cohort_id=inputs.cohort_id,
                condition=inputs.condition,
                min_matches=inputs.min_matches,
                days=inputs.days,
                limit=limit,
                offset=offset,
                conditions_page_size=min(1000, limit),  # Don't fetch more than we need
            )

            # Start child workflow - fire and forget, don't wait for result
            # Set parent_close_policy to ABANDON so child workflows continue after parent completes
            await temporalio.workflow.start_child_workflow(
                BehavioralCohortsWorkflow.run,
                child_inputs,
                id=child_id,
                task_queue=MESSAGING_TASK_QUEUE,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
            )
            workflows_scheduled += 1

            workflow_logger.info(f"Scheduled child workflow {i+1} for conditions {offset}-{offset+limit-1}")

        workflow_logger.info(f"Coordinator completed: scheduled {workflows_scheduled} child workflows")
        return
