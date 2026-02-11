import math
import asyncio
import datetime as dt
import dataclasses
from typing import Any, Optional, TypedDict

from django.conf import settings

import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.models.cohort.cohort import Cohort, CohortType
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.constants import get_child_workflow_id
from posthog.temporal.messaging.realtime_cohort_calculation_workflow import (
    RealtimeCohortCalculationWorkflow,
    RealtimeCohortCalculationWorkflowInputs,
)

LOGGER = get_logger(__name__)


class WorkflowConfig(TypedDict):
    """Type definition for workflow configuration."""

    id: str
    inputs: RealtimeCohortCalculationWorkflowInputs
    index: int


@dataclasses.dataclass
class RealtimeCohortCalculationCoordinatorWorkflowInputs:
    """Inputs for the coordinator workflow that spawns child workflows."""

    parallelism: int = 10  # Number of child workflows to spawn
    workflows_per_batch: int = 5  # Number of workflows to start per batch
    batch_delay_minutes: int = 5  # Delay between batches in minutes
    cohort_id: Optional[int] = None  # Filter to a specific cohort_id (optional)
    # Teams that should process all cohorts, and global percentage for teams not in team_ids
    team_ids: Optional[set[int]] = (
        None  # Teams that process all cohorts (if empty/None, all teams use global_percentage)
    )
    global_percentage: Optional[float] = (
        None  # Percentage of cohorts for non-listed teams, or for all teams if team_ids is empty/None
    )

    def __post_init__(self):
        """Load default configuration from environment if not provided."""
        if self.team_ids is None:
            from posthog.settings.schedules import REALTIME_COHORT_CALCULATION_TEAMS

            self.team_ids = REALTIME_COHORT_CALCULATION_TEAMS.copy()

        if self.global_percentage is None:
            from posthog.settings.schedules import REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE

            self.global_percentage = REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "parallelism": self.parallelism,
            "workflows_per_batch": self.workflows_per_batch,
            "batch_delay_minutes": self.batch_delay_minutes,
            "cohort_id": self.cohort_id,
            "team_ids": list(self.team_ids) if self.team_ids else [],
            "global_percentage": self.global_percentage,
        }


@dataclasses.dataclass
class RealtimeCohortCalculationCountResult:
    """Result from counting total cohorts."""

    count: int


@dataclasses.dataclass
class RealtimeCohortSelectionResult:
    """Result from selecting cohorts with filtering applied."""

    cohort_ids: list[int]


@temporalio.activity.defn
async def get_realtime_cohort_calculation_count_activity(
    inputs: RealtimeCohortCalculationCoordinatorWorkflowInputs,
) -> RealtimeCohortCalculationCountResult:
    """Get the total count of realtime cohorts."""

    @database_sync_to_async
    def get_cohort_count():
        # If cohort_id is specified, just count that specific cohort
        if inputs.cohort_id is not None:
            queryset = Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME, id=inputs.cohort_id)
            return queryset.count()

        total_count = 0

        # First, process teams that should include all cohorts
        if inputs.team_ids:
            for team_id in inputs.team_ids:
                if not isinstance(team_id, int) or team_id <= 0:
                    continue  # Skip invalid team IDs
                team_cohorts_count = Cohort.objects.filter(
                    deleted=False, cohort_type=CohortType.REALTIME, team_id=team_id
                ).count()
                total_count += team_cohorts_count

        # Handle global percentage for all other teams
        if inputs.global_percentage is not None and inputs.global_percentage > 0.0 and inputs.global_percentage <= 1.0:
            # Get cohorts from teams not in the force list
            if inputs.team_ids:
                other_teams_cohorts_count = (
                    Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME)
                    .exclude(team_id__in=inputs.team_ids)
                    .count()
                )
            else:
                other_teams_cohorts_count = Cohort.objects.filter(
                    deleted=False, cohort_type=CohortType.REALTIME
                ).count()

            if other_teams_cohorts_count > 0:
                # Apply global percentage to other teams' cohorts
                num_to_include = int(other_teams_cohorts_count * inputs.global_percentage)
                total_count += min(num_to_include, other_teams_cohorts_count)

        return total_count

    count = await get_cohort_count()
    return RealtimeCohortCalculationCountResult(count=count)


@temporalio.activity.defn
async def get_realtime_cohort_selection_activity(
    inputs: RealtimeCohortCalculationCoordinatorWorkflowInputs,
) -> RealtimeCohortSelectionResult:
    """Get the actual list of cohort IDs to process based on filtering criteria."""

    @database_sync_to_async
    def get_selected_cohort_ids():
        # If cohort_id is specified, just return that specific cohort ID if it exists
        if inputs.cohort_id is not None:
            cohort_exists = Cohort.objects.filter(
                deleted=False, cohort_type=CohortType.REALTIME, id=inputs.cohort_id
            ).exists()
            return [inputs.cohort_id] if cohort_exists else []

        selected_cohort_ids = []

        # Step 1: Add cohort IDs for teams that should process everything
        if inputs.team_ids:
            for team_id in inputs.team_ids:
                if not isinstance(team_id, int) or team_id <= 0:
                    continue  # Skip invalid team IDs
                team_cohort_ids = list(
                    Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME, team_id=team_id)
                    .order_by("id")
                    .values_list("id", flat=True)
                )
                selected_cohort_ids.extend(team_cohort_ids)

        # Step 2: Add sampled cohort IDs for global percentage (other teams)
        if inputs.global_percentage and inputs.global_percentage > 0.0 and inputs.global_percentage <= 1.0:
            # Get cohort IDs from teams not in the force list
            if inputs.team_ids:
                other_teams_cohort_ids = list(
                    Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME)
                    .exclude(team_id__in=inputs.team_ids)
                    .order_by("id")
                    .values_list("id", flat=True)
                )
            else:
                other_teams_cohort_ids = list(
                    Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME)
                    .order_by("id")
                    .values_list("id", flat=True)
                )

            if other_teams_cohort_ids:
                # Apply global percentage - SAME LOGIC AS COUNT ACTIVITY
                num_to_include = int(len(other_teams_cohort_ids) * inputs.global_percentage)
                if num_to_include > 0:
                    # Take the first N cohort IDs for deterministic selection
                    selected_other_cohort_ids = other_teams_cohort_ids[:num_to_include]
                    selected_cohort_ids.extend(selected_other_cohort_ids)

        # Step 3: Remove duplicates while preserving order
        seen_ids = set()
        unique_cohort_ids = []
        for cohort_id in selected_cohort_ids:
            if cohort_id not in seen_ids:
                seen_ids.add(cohort_id)
                unique_cohort_ids.append(cohort_id)

        # Step 4: Sort by ID for consistent distribution
        unique_cohort_ids.sort()
        return unique_cohort_ids

    cohort_ids = await get_selected_cohort_ids()
    return RealtimeCohortSelectionResult(cohort_ids=cohort_ids)


@temporalio.workflow.defn(name="realtime-cohort-calculation-coordinator")
class RealtimeCohortCalculationCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that spawns multiple child workflows for true parallelism."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RealtimeCohortCalculationCoordinatorWorkflowInputs:
        """Parse inputs from the management command CLI."""
        return RealtimeCohortCalculationCoordinatorWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: RealtimeCohortCalculationCoordinatorWorkflowInputs) -> None:
        """Run the coordinator workflow that spawns child workflows."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(f"Starting realtime cohort calculation coordinator with parallelism={inputs.parallelism}")

        # Step 1: Get selected cohort IDs based on filtering criteria
        selection_result = await temporalio.workflow.execute_activity(
            get_realtime_cohort_selection_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        all_cohort_ids = selection_result.cohort_ids
        if not all_cohort_ids:
            workflow_logger.warning("No realtime cohorts found matching selection criteria")
            return

        total_cohorts = len(all_cohort_ids)
        workflow_logger.info(
            f"Distributing {total_cohorts} selected cohorts across {inputs.parallelism} child workflows "
            f"in batches of {inputs.workflows_per_batch} every {inputs.batch_delay_minutes} minutes"
        )

        # Step 2: Distribute cohort IDs across workers
        cohorts_per_workflow = math.ceil(total_cohorts / inputs.parallelism)

        # Step 3: Prepare all workflow configs with specific cohort ID lists
        workflow_configs: list[WorkflowConfig] = []
        for i in range(inputs.parallelism):
            start_idx = i * cohorts_per_workflow
            end_idx = min(start_idx + cohorts_per_workflow, total_cohorts)

            if start_idx >= total_cohorts:
                break

            # Get the specific cohort IDs for this worker
            worker_cohort_ids = all_cohort_ids[start_idx:end_idx]

            if not worker_cohort_ids:
                continue  # Skip empty ranges

            workflow_configs.append(
                WorkflowConfig(
                    id=get_child_workflow_id(temporalio.workflow.info().workflow_id, i),
                    inputs=RealtimeCohortCalculationWorkflowInputs(
                        cohort_ids=worker_cohort_ids,
                        cohort_id=inputs.cohort_id,  # Keep for backward compatibility
                    ),
                    index=i + 1,
                )
            )

        total_workflows = len(workflow_configs)
        workflow_logger.info(f"Prepared {total_workflows} workflow configurations")

        # Step 4: Launch workflows in batches and collect handles
        child_workflow_handles = []
        workflows_scheduled = 0
        for batch_start in range(0, total_workflows, inputs.workflows_per_batch):
            batch_end = min(batch_start + inputs.workflows_per_batch, total_workflows)
            batch_configs = workflow_configs[batch_start:batch_end]
            batch_number = (batch_start // inputs.workflows_per_batch) + 1
            total_batches = math.ceil(total_workflows / inputs.workflows_per_batch)

            workflow_logger.info(
                f"Starting batch {batch_number}/{total_batches}: scheduling {len(batch_configs)} workflows"
            )

            # Start all workflows in current batch and collect handles
            for config in batch_configs:
                child_handle = await temporalio.workflow.start_child_workflow(
                    RealtimeCohortCalculationWorkflow.run,
                    config["inputs"],
                    id=config["id"],
                    task_queue=settings.MESSAGING_TASK_QUEUE,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
                child_workflow_handles.append(child_handle)
                workflows_scheduled += 1

                workflow_logger.info(
                    f"Scheduled workflow {config['index']} for {len(config['inputs'].cohort_ids)} cohorts: {config['inputs'].cohort_ids[:5]}{'...' if len(config['inputs'].cohort_ids) > 5 else ''}"
                )

            workflow_logger.info(
                f"Batch {batch_number}/{total_batches} completed: {len(batch_configs)} workflows started "
                f"({workflows_scheduled}/{total_workflows} total)"
            )

            # Wait before starting next batch (unless this is the last batch)
            if batch_end < total_workflows:
                delay_seconds = inputs.batch_delay_minutes * 60
                workflow_logger.info(f"Waiting {inputs.batch_delay_minutes} minutes before starting next batch...")
                await temporalio.workflow.sleep(delay_seconds)

        workflow_logger.info(f"All {workflows_scheduled} child workflows scheduled, waiting for completion...")

        # Step 5: Wait for all child workflows to complete
        completed_count = 0
        failed_count = 0

        workflow_logger.info(f"Waiting for {len(child_workflow_handles)} child workflows to complete...")
        for handle in asyncio.as_completed(child_workflow_handles):
            try:
                await handle  # Get the result (raises if failed)
                completed_count += 1
                workflow_logger.info(
                    f"Child workflow completed successfully ({completed_count + failed_count}/{workflows_scheduled})"
                )
            except Exception as e:
                failed_count += 1
                workflow_logger.exception(
                    f"Child workflow failed ({completed_count + failed_count}/{workflows_scheduled}): {e}"
                )

        workflow_logger.info(f"Coordinator completed: {completed_count} succeeded, {failed_count} failed")
        return
