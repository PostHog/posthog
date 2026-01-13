"""Coordinator workflow for video segment clustering.

This workflow discovers teams with the feature flag enabled and spawns
child workflows to cluster video segments for each team.
"""

import asyncio
import dataclasses
from typing import Any

import structlog
import temporalio
from temporalio.workflow import ChildWorkflowHandle

from posthog.models.feature_flag import FeatureFlag
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import ClusteringWorkflowInputs, WorkflowResult
from posthog.temporal.ai.video_segment_clustering.workflow import VideoSegmentClusteringWorkflow
from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class VideoSegmentClusteringCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    lookback_hours: int = int(constants.DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600)
    min_segments: int = constants.MIN_SEGMENTS_FOR_CLUSTERING
    max_concurrent_teams: int = constants.MAX_CONCURRENT_TEAMS


def get_enabled_team_ids() -> list[int]:
    """Get team IDs with video-segment-clustering-enabled feature flag.

    Uses PostHog feature flags to control rollout.

    Returns:
        List of team IDs with the feature flag enabled
    """
    try:
        # Find all teams where the feature flag is enabled
        # This queries flags that match our key and are active
        flags = FeatureFlag.objects.filter(
            key=constants.FEATURE_FLAG_KEY,
            active=True,
            deleted=False,
        ).select_related("team")

        # For simplicity, return team IDs where the flag exists and is active
        # A more sophisticated approach would evaluate the flag conditions
        team_ids = [flag.team_id for flag in flags]

        return team_ids

    except Exception as e:
        logger.warning(
            "Failed to query feature flags, using empty list",
            error=str(e),
        )
        return []


@temporalio.workflow.defn(name="video-segment-clustering-coordinator")
class VideoSegmentClusteringCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that discovers teams via feature flag and spawns child workflows.

    This runs on a schedule (every 30 minutes) and processes video segments
    for teams that have the feature flag enabled.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> VideoSegmentClusteringCoordinatorInputs:
        """Parse workflow inputs from string list."""
        return VideoSegmentClusteringCoordinatorInputs(
            lookback_hours=int(inputs[0])
            if len(inputs) > 0
            else int(constants.DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600),
            min_segments=int(inputs[1]) if len(inputs) > 1 else constants.MIN_SEGMENTS_FOR_CLUSTERING,
            max_concurrent_teams=int(inputs[2]) if len(inputs) > 2 else constants.MAX_CONCURRENT_TEAMS,
        )

    @temporalio.workflow.run
    async def run(self, inputs: VideoSegmentClusteringCoordinatorInputs) -> dict[str, Any]:
        """Execute coordinator workflow."""
        logger.info(
            "Starting video segment clustering coordinator",
            lookback_hours=inputs.lookback_hours,
            min_segments=inputs.min_segments,
        )

        # Get teams from feature flag
        team_ids = await temporalio.workflow.execute_activity(
            "discover_enabled_teams",
            start_to_close_timeout=constants.FETCH_ACTIVITY_TIMEOUT,
        )

        if not team_ids:
            logger.info("No teams enabled for video segment clustering")
            return {
                "teams_processed": 0,
                "total_tasks_created": 0,
                "total_tasks_updated": 0,
            }

        logger.info(
            "Processing teams for video segment clustering",
            team_count=len(team_ids),
            team_ids=team_ids,
        )

        # Process metrics
        total_segments = 0
        total_clusters = 0
        total_tasks_created = 0
        total_tasks_updated = 0
        failed_teams: list[int] = []
        successful_teams: list[int] = []

        # Process teams in batches for controlled parallelism
        max_concurrent = inputs.max_concurrent_teams

        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            # Start all workflows in batch concurrently
            workflow_handles: list[tuple[int, ChildWorkflowHandle[VideoSegmentClusteringWorkflow, WorkflowResult]]] = []

            for team_id in batch:
                handle = await temporalio.workflow.start_child_workflow(
                    VideoSegmentClusteringWorkflow.run,
                    ClusteringWorkflowInputs(
                        team_id=team_id,
                        lookback_hours=inputs.lookback_hours,
                        min_segments=inputs.min_segments,
                    ),
                    id=f"video-segment-clustering-team-{team_id}-{temporalio.workflow.now().isoformat()}",
                    execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
                    retry_policy=constants.COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
                workflow_handles.append((team_id, handle))

            # Wait for all workflows in batch to complete
            for team_id, handle in workflow_handles:
                try:
                    workflow_result: WorkflowResult = await handle

                    if workflow_result.success:
                        total_segments += workflow_result.segments_processed
                        total_clusters += workflow_result.clusters_found
                        total_tasks_created += workflow_result.tasks_created
                        total_tasks_updated += workflow_result.tasks_updated
                        successful_teams.append(team_id)

                        logger.info(
                            "Completed clustering for team",
                            team_id=team_id,
                            segments=workflow_result.segments_processed,
                            clusters=workflow_result.clusters_found,
                            tasks_created=workflow_result.tasks_created,
                            tasks_updated=workflow_result.tasks_updated,
                        )
                    else:
                        failed_teams.append(team_id)
                        logger.warning(
                            "Clustering failed for team",
                            team_id=team_id,
                            error=workflow_result.error,
                        )

                except Exception:
                    logger.exception("Failed to cluster team", team_id=team_id)
                    failed_teams.append(team_id)

        logger.info(
            "Video segment clustering coordinator completed",
            teams_processed=len(team_ids),
            teams_succeeded=len(successful_teams),
            teams_failed=len(failed_teams),
            total_segments=total_segments,
            total_clusters=total_clusters,
            total_tasks_created=total_tasks_created,
            total_tasks_updated=total_tasks_updated,
        )

        return {
            "teams_processed": len(team_ids),
            "teams_succeeded": len(successful_teams),
            "teams_failed": len(failed_teams),
            "failed_team_ids": failed_teams,
            "total_segments": total_segments,
            "total_clusters": total_clusters,
            "total_tasks_created": total_tasks_created,
            "total_tasks_updated": total_tasks_updated,
        }


# Activity for discovering enabled teams (needs to be in a separate activity
# because we can't make DB queries directly in workflows)
@temporalio.activity.defn(name="discover_enabled_teams")
async def discover_enabled_teams_activity() -> list[int]:
    """Activity to discover teams with the feature flag enabled."""
    return await asyncio.to_thread(get_enabled_team_ids)
