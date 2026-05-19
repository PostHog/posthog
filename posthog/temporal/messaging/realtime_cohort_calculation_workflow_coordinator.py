import math
import random
import asyncio
import datetime as dt
import dataclasses
from typing import Any, Optional, TypedDict

from django.conf import settings
from django.db.models import F
from django.utils import timezone

import temporalio.common
import temporalio.activity
import temporalio.workflow
from temporalio.common import MetricHistogramFloat

from posthog.models.cohort.cohort import Cohort, CohortType
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.constants import get_child_workflow_id, get_percentile_bucket_label
from posthog.temporal.messaging.quantiles_storage import get_cached_quantiles_or_calculate
from posthog.temporal.messaging.realtime_cohort_calculation_workflow import (
    RealtimeCohortCalculationWorkflow,
    RealtimeCohortCalculationWorkflowInputs,
)

LOGGER = get_logger(__name__)


def get_coordinator_duration_histogram(percentile_bucket: str) -> MetricHistogramFloat:
    """Histogram for coordinator workflow total duration by percentile bucket."""
    return (
        temporalio.workflow.metric_meter()
        .with_additional_attributes({"percentile_bucket": percentile_bucket})
        .create_histogram_float(
            "realtime_cohort_coordinator_duration_seconds",
            "Total duration of coordinator workflow execution in seconds",
            "s",
        )
    )


@dataclasses.dataclass
class QueryPercentileThresholdsInput:
    """Input for querying percentile thresholds."""

    min_percentile: Optional[float] = None  # e.g., 0.0 for p0
    max_percentile: Optional[float] = None  # e.g., 90.0 for p90


@dataclasses.dataclass
class QueryPercentileThresholds:
    """Query duration percentile thresholds for cohort filtering."""

    min_threshold_ms: int = 0  # Threshold for the minimum percentile (milliseconds)
    max_threshold_ms: int = 0  # Threshold for the maximum percentile (milliseconds)


@dataclasses.dataclass
class CohortSelectionActivityInput:
    """Combined input for get_realtime_cohort_selection_activity."""

    coordinator_inputs: "RealtimeCohortCalculationCoordinatorWorkflowInputs"
    query_percentile_thresholds: QueryPercentileThresholds | None = None


def _apply_duration_filtering(queryset, thresholds: QueryPercentileThresholds | None, is_p100: bool = False):
    """Apply duration filtering to cohort queryset based on percentile thresholds.

    Args:
        queryset: Django queryset of Cohort objects
        thresholds: Percentile thresholds containing min/max duration bounds

    Returns:
        Filtered queryset

    Note:
        - When is_p100=True, only lower bound is applied and NULL durations are included
        - This allows new cohorts (without duration data) to be included in the slowest tier
    """
    if not thresholds:
        return queryset

    min_threshold_ms = thresholds.min_threshold_ms
    max_threshold_ms = thresholds.max_threshold_ms

    # Special case: if this is p100 (no upper limit), only apply lower bound
    # and include cohorts without duration data (NULL values)
    if is_p100:
        # Include cohorts that are either:
        # 1. Have duration >= min_threshold, OR
        # 2. Have NULL duration (haven't been calculated yet)
        from django.db.models import Q

        filter_condition = Q(last_calculation_duration_ms__gte=min_threshold_ms) | Q(
            last_calculation_duration_ms__isnull=True
        )
        return queryset.filter(filter_condition)
    else:
        # Normal case: apply both upper and lower bounds
        # Only include cohorts with duration data in the specified range

        # Handle edge case: when all cohorts have identical/similar durations,
        # quantile boundaries may be identical (min_threshold_ms == max_threshold_ms).
        # Using __lt would match zero rows, so use __lte for the upper bound instead.
        if min_threshold_ms == max_threshold_ms:
            return queryset.filter(
                last_calculation_duration_ms__gte=min_threshold_ms, last_calculation_duration_ms__lte=max_threshold_ms
            )
        else:
            return queryset.filter(
                last_calculation_duration_ms__gte=min_threshold_ms, last_calculation_duration_ms__lt=max_threshold_ms
            )


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
    duration_percentile_min: Optional[float] = None  # Minimum duration percentile threshold (e.g., 0.0)
    duration_percentile_max: Optional[float] = None  # Maximum duration percentile threshold (e.g., 90.0)

    # Note: __post_init__ was removed to ensure Temporal workflow determinism.
    # Django settings values (team_ids, global_percentage) are now loaded at schedule
    # creation time rather than during deserialization to prevent non-deterministic
    # behavior across workers and during replays.

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "parallelism": self.parallelism,
            "workflows_per_batch": self.workflows_per_batch,
            "batch_delay_minutes": self.batch_delay_minutes,
            "cohort_id": self.cohort_id,
            "team_ids": list(self.team_ids) if self.team_ids else [],
            "global_percentage": self.global_percentage,
            "duration_percentile_min": self.duration_percentile_min,
            "duration_percentile_max": self.duration_percentile_max,
        }


@dataclasses.dataclass
class RealtimeCohortSelectionResult:
    """Result from selecting cohorts with filtering applied."""

    cohort_ids: list[int]


async def calculate_percentile_thresholds(
    inputs: QueryPercentileThresholdsInput,
) -> QueryPercentileThresholds | None:
    """Calculate percentile thresholds using cached quantiles to ensure consistency across workflows."""

    @database_sync_to_async
    def get_thresholds():
        try:
            # Get cohorts with recent duration data (past 24 hours)
            recent_cohorts = Cohort.objects.filter(
                last_calculation__gte=timezone.now() - dt.timedelta(hours=24),
                last_calculation_duration_ms__isnull=False,
                last_calculation_duration_ms__gt=0,
                deleted=False,
            ).values_list("last_calculation_duration_ms", flat=True)

            if not recent_cohorts:
                return None

            durations_list = list(recent_cohorts)

            # Calculate specific percentile thresholds
            min_percentile = inputs.min_percentile
            max_percentile = inputs.max_percentile

            # Get quantiles from cache or calculate atomically
            # This ensures all workflows use the same percentile boundaries
            # Check cache first even if current query has insufficient data
            cached = get_cached_quantiles_or_calculate(durations_list)

            if cached is None:
                LOGGER.warning("Failed to get or calculate quantiles")
                # Emit metric for monitoring quantiles unavailability.
                # This runs inside an activity, so use the activity meter rather than the
                # workflow meter (which would raise outside a workflow event loop).
                try:
                    quantiles_unavailable_counter = temporalio.activity.metric_meter().create_counter(
                        "quantiles_unavailable", "Count of times quantiles were unavailable for percentile calculations"
                    )
                    quantiles_unavailable_counter.add(1)
                except RuntimeError:
                    # Not in activity context (e.g., during tests), skip metric
                    pass
                return None

            quantiles = cached.quantiles
            cached_max = cached.max_value

            # Special handling for p0: use 0 instead of calculating from data
            if min_percentile is None or min_percentile <= 0.0:
                min_threshold = 0
            elif min_percentile >= 99.9:
                # p100 case - use cached max so all workflows sharing this cache entry
                # get identical p100 boundaries even if current durations_list differs.
                min_threshold = cached_max
            else:
                # For percentiles 1-99, quantiles[0] is p1, quantiles[1] is p2, etc.
                min_threshold = int(quantiles[int(min_percentile) - 1])

            # Calculate max threshold
            if max_percentile is None or max_percentile >= 99.9:
                # p100 case - use cached max for cross-workflow consistency.
                max_threshold = cached_max
            else:
                # For percentiles 1-99, quantiles[0] is p1, quantiles[1] is p2, etc.
                max_threshold = int(quantiles[int(max_percentile) - 1])

            return QueryPercentileThresholds(
                min_threshold_ms=min_threshold,
                max_threshold_ms=max_threshold,
            )

        except (TypeError, ValueError, IndexError) as e:
            LOGGER.warning(
                "Failed to calculate percentile thresholds from cached quantiles",
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    return await get_thresholds()


@temporalio.activity.defn
async def get_query_percentile_thresholds_activity(
    inputs: QueryPercentileThresholdsInput,
) -> QueryPercentileThresholds | None:
    """Get query duration percentile thresholds by calculating directly from duration data."""
    return await calculate_percentile_thresholds(inputs)


@temporalio.activity.defn
async def get_realtime_cohort_selection_activity(
    activity_inputs: CohortSelectionActivityInput,
) -> RealtimeCohortSelectionResult:
    """Get the actual list of cohort IDs to process based on filtering criteria."""

    # Extract values from combined input
    inputs = activity_inputs.coordinator_inputs
    query_percentile_thresholds = activity_inputs.query_percentile_thresholds

    @database_sync_to_async
    def get_selected_cohort_ids():
        # Log duration percentile filtering status
        thresholds = query_percentile_thresholds

        # If cohort_id is specified, just return that specific cohort ID if it exists
        # (No duration filtering when manually specifying cohort_id via Django command)
        if inputs.cohort_id is not None:
            cohort_exists = Cohort.objects.filter(
                deleted=False, cohort_type=CohortType.REALTIME, id=inputs.cohort_id
            ).exists()
            return [inputs.cohort_id] if cohort_exists else []

        selected_cohort_ids = []

        # Step 1: Add cohort IDs for teams that should process everything
        if inputs.team_ids:
            # Filter out invalid team IDs
            valid_team_ids = [team_id for team_id in inputs.team_ids if isinstance(team_id, int) and team_id > 0]

            if valid_team_ids:
                # Single query for all valid teams instead of N queries
                team_cohort_queryset = Cohort.objects.filter(
                    deleted=False, cohort_type=CohortType.REALTIME, team_id__in=valid_team_ids
                )
                # Apply duration filtering only in scheduled mode (when percentile thresholds are available)
                if thresholds and (
                    inputs.duration_percentile_min is not None or inputs.duration_percentile_max is not None
                ):
                    team_cohort_queryset = _apply_duration_filtering(
                        team_cohort_queryset,
                        thresholds,
                        is_p100=(inputs.duration_percentile_max is not None and inputs.duration_percentile_max >= 99.9),
                    )
                team_cohort_ids = list(
                    team_cohort_queryset.order_by(
                        F("last_calculation_duration_ms").asc(nulls_last=True), "id"
                    ).values_list("id", flat=True)
                )

                selected_cohort_ids.extend(team_cohort_ids)

        # Step 2: Add sampled cohort IDs for global percentage (other teams)
        if inputs.global_percentage and inputs.global_percentage > 0.0 and inputs.global_percentage <= 1.0:
            # Get cohort IDs from teams not in the force list
            if inputs.team_ids:
                other_teams_queryset = Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME).exclude(
                    team_id__in=inputs.team_ids
                )
            else:
                other_teams_queryset = Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME)

            # Apply duration filtering only in scheduled mode (when percentile thresholds are available)
            if thresholds and (
                inputs.duration_percentile_min is not None or inputs.duration_percentile_max is not None
            ):
                other_teams_queryset = _apply_duration_filtering(
                    other_teams_queryset,
                    thresholds,
                    is_p100=(inputs.duration_percentile_max is not None and inputs.duration_percentile_max >= 99.9),
                )
            other_teams_cohort_ids = list(
                other_teams_queryset.order_by(F("last_calculation_duration_ms").asc(nulls_last=True), "id").values_list(
                    "id", flat=True
                )
            )

            if other_teams_cohort_ids:
                # Apply global percentage with random sampling
                num_to_include = int(len(other_teams_cohort_ids) * inputs.global_percentage)
                if num_to_include > 0:
                    # Randomly sample cohorts to ensure fair distribution over time
                    selected_other_cohort_ids = random.sample(other_teams_cohort_ids, num_to_include)
                    selected_cohort_ids.extend(selected_other_cohort_ids)

        # Step 3: Remove duplicates while preserving order
        seen_ids = set()
        unique_cohort_ids = []
        for cohort_id in selected_cohort_ids:
            if cohort_id not in seen_ids:
                seen_ids.add(cohort_id)
                unique_cohort_ids.append(cohort_id)

        # Step 4: Return with duration-based ordering preserved for effective load balancing
        return unique_cohort_ids

    cohort_ids = await get_selected_cohort_ids()
    return RealtimeCohortSelectionResult(cohort_ids=cohort_ids)


@temporalio.workflow.defn(name="realtime-cohort-calculation-coordinator")
class RealtimeCohortCalculationCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that spawns multiple child workflows for true parallelism."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RealtimeCohortCalculationCoordinatorWorkflowInputs:
        """Parse inputs from the management command CLI."""
        from posthog.settings.schedules import (
            REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE,
            REALTIME_COHORT_CALCULATION_TEAMS,
        )

        return RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids=REALTIME_COHORT_CALCULATION_TEAMS.copy(),
            global_percentage=REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE,
        )

    @temporalio.workflow.run
    async def run(self, inputs: RealtimeCohortCalculationCoordinatorWorkflowInputs) -> None:
        """Run the coordinator workflow that spawns child workflows."""
        coordinator_start_time = temporalio.workflow.time()
        percentile_bucket = get_percentile_bucket_label(inputs.duration_percentile_min, inputs.duration_percentile_max)

        workflow_logger = temporalio.workflow.logger
        workflow_logger.info("Starting realtime cohort calculation coordinator", parallelism=inputs.parallelism)
        workflow_logger.info(
            "Cohort selection config", team_ids=inputs.team_ids, global_percentage=inputs.global_percentage
        )

        # Log duration percentile filtering parameters
        if inputs.duration_percentile_min is not None or inputs.duration_percentile_max is not None:
            min_p = inputs.duration_percentile_min if inputs.duration_percentile_min is not None else 0.0
            max_p = inputs.duration_percentile_max if inputs.duration_percentile_max is not None else 100.0
            workflow_logger.info("Duration percentile filtering", min_percentile=min_p, max_percentile=max_p)

            # Get actual query percentile thresholds from the last 24 hours
            thresholds_input = QueryPercentileThresholdsInput(
                min_percentile=inputs.duration_percentile_min,
                max_percentile=inputs.duration_percentile_max,
            )
            thresholds = await temporalio.workflow.execute_activity(
                get_query_percentile_thresholds_activity,
                thresholds_input,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
            if thresholds:
                workflow_logger.info(
                    f"Query duration thresholds from last 24h: p{min_p}={thresholds.min_threshold_ms / 1000:.2f}s, "
                    f"p{max_p}={thresholds.max_threshold_ms / 1000:.2f}s"
                )
            else:
                workflow_logger.info(
                    f"Duration percentile filtering p{min_p}-p{max_p}: disabled (no historical query data)"
                )
        else:
            workflow_logger.info("Duration percentile filtering: disabled (processing all cohorts)")
            thresholds = None

        # Early exit for higher percentile schedules when insufficient duration data
        # This prevents tripling the workload during feature launch when all schedules
        # would otherwise process every cohort
        if thresholds is None and inputs.duration_percentile_min is not None and inputs.duration_percentile_min >= 90.0:
            min_p = inputs.duration_percentile_min if inputs.duration_percentile_min is not None else 0.0
            max_p = inputs.duration_percentile_max if inputs.duration_percentile_max is not None else 100.0
            workflow_logger.info(
                f"Skipping p{min_p}-p{max_p} schedule execution: insufficient duration data for percentile filtering"
            )
            return

        # Early exit for higher percentile schedules when all durations are identical
        # This prevents multiple schedules from processing the same cohorts when
        # min_threshold_ms == max_threshold_ms (all tiers would match the same set)
        if (
            thresholds is not None
            and thresholds.min_threshold_ms == thresholds.max_threshold_ms
            and inputs.duration_percentile_min is not None
            and inputs.duration_percentile_min >= 90.0
        ):
            min_p = inputs.duration_percentile_min if inputs.duration_percentile_min is not None else 0.0
            max_p = inputs.duration_percentile_max if inputs.duration_percentile_max is not None else 100.0
            workflow_logger.info(
                f"Skipping p{min_p}-p{max_p} schedule execution: identical duration thresholds "
                f"({thresholds.min_threshold_ms}ms) would cause duplicate processing across tiers"
            )
            return

        # Step 1: Get selected cohort IDs based on filtering criteria
        selection_activity_input = CohortSelectionActivityInput(
            coordinator_inputs=inputs,
            query_percentile_thresholds=thresholds,
        )
        selection_result = await temporalio.workflow.execute_activity(
            get_realtime_cohort_selection_activity,
            selection_activity_input,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        all_cohort_ids = selection_result.cohort_ids

        # Check for empty results after cohort selection
        if not all_cohort_ids:
            workflow_logger.warning("No realtime cohorts found matching selection criteria")
            return

        total_cohorts = len(all_cohort_ids)
        workflow_logger.info(
            f"Distributing {total_cohorts} selected cohorts across {inputs.parallelism} child workflows "
            f"in batches of {inputs.workflows_per_batch} every {inputs.batch_delay_minutes} minutes"
        )

        # Step 2: Distribute cohort IDs using round-robin to balance workload
        # This distributes cohorts ordered by duration across workers to prevent
        # any single worker from getting all the slow cohorts

        # Initialize lists for each worker
        worker_cohort_lists: list[list[int]] = [[] for _ in range(inputs.parallelism)]

        # Distribute cohorts round-robin style
        for idx, cohort_id in enumerate(all_cohort_ids):
            worker_idx = idx % inputs.parallelism
            worker_cohort_lists[worker_idx].append(cohort_id)

        # Step 3: Prepare all workflow configs with balanced cohort ID lists
        workflow_configs: list[WorkflowConfig] = []
        for i in range(inputs.parallelism):
            worker_cohort_ids = worker_cohort_lists[i]

            if not worker_cohort_ids:
                continue  # Skip workers with no cohorts

            workflow_configs.append(
                WorkflowConfig(
                    id=get_child_workflow_id(temporalio.workflow.info().workflow_id, i),
                    inputs=RealtimeCohortCalculationWorkflowInputs(
                        cohort_ids=worker_cohort_ids,
                        cohort_id=inputs.cohort_id,  # Keep for backward compatibility
                        duration_percentile_min=inputs.duration_percentile_min,
                        duration_percentile_max=inputs.duration_percentile_max,
                    ),
                    index=i + 1,
                )
            )

        total_workflows = len(workflow_configs)
        workflow_logger.info("Prepared workflow configurations", total_workflows=total_workflows)

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

                cohort_ids = config["inputs"].cohort_ids
                if cohort_ids is not None:
                    workflow_logger.info(
                        f"Scheduled workflow {config['index']} for {len(cohort_ids)} cohorts: {cohort_ids[:5]}{'...' if len(cohort_ids) > 5 else ''}"
                    )
                else:
                    workflow_logger.info(
                        f"Scheduled workflow {config['index']} for single cohort: {config['inputs'].cohort_id}"
                    )

            workflow_logger.info(
                f"Batch {batch_number}/{total_batches} completed: {len(batch_configs)} workflows started "
                f"({workflows_scheduled}/{total_workflows} total)"
            )

            # Wait before starting next batch (unless this is the last batch)
            if batch_end < total_workflows:
                delay_seconds = inputs.batch_delay_minutes * 60
                workflow_logger.info("Waiting before starting next batch", delay_minutes=inputs.batch_delay_minutes)
                await temporalio.workflow.sleep(delay_seconds)

        workflow_logger.info(
            "All child workflows scheduled, waiting for completion", workflows_scheduled=workflows_scheduled
        )

        # Step 5: Wait for all child workflows to complete
        completed_count = 0
        failed_count = 0

        workflow_logger.info("Waiting for child workflows to complete", total_workflows=len(child_workflow_handles))
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

        coordinator_duration = temporalio.workflow.time() - coordinator_start_time
        get_coordinator_duration_histogram(percentile_bucket).record(coordinator_duration)

        workflow_logger.info(
            f"Coordinator completed in {coordinator_duration:.1f}s",
            succeeded=completed_count,
            failed=failed_count,
            total_duration_seconds=coordinator_duration,
        )
        return
