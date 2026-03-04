"""
Coordinator workflow for video segment clustering.

This workflow processes video segments for teams with proactive tasks enabled
and spawns child workflows to cluster segments for each team.
"""

import json
import dataclasses
from datetime import timedelta
from typing import Any

import structlog
import temporalio
import posthoganalytics
import temporalio.exceptions
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.workflow import ChildWorkflowHandle

from posthog.temporal.ai.video_segment_clustering.clustering_workflow import VideoSegmentClusteringWorkflow
from posthog.temporal.ai.video_segment_clustering.constants import DEFAULT_LOOKBACK_WINDOW, clustering_workflow_id
from posthog.temporal.ai.video_segment_clustering.models import ClusteringWorkflowInputs, EmitSignalsResult
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)
activity_logger = get_logger(__name__)

# Coordinator constants
DEFAULT_MAX_CONCURRENT_TEAMS = 50


@dataclasses.dataclass
class VideoSegmentClusteringCoordinatorInputs:
    lookback_hours: int = int(DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600)


@temporalio.workflow.defn(name="video-segment-clustering-coordinator")
class VideoSegmentClusteringCoordinatorWorkflow(PostHogWorkflow):
    """
    This runs on schedule and kicks off task inference (creating proactive tasks) for teams with proactive_tasks_enabled.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> VideoSegmentClusteringCoordinatorInputs:
        loaded = json.loads(inputs[0])
        return VideoSegmentClusteringCoordinatorInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: VideoSegmentClusteringCoordinatorInputs) -> dict[str, Any]:
        enabled_configs: list[tuple[int, str]] = await workflow.execute_activity(
            get_proactive_tasks_enabled_team_ids_activity,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
            ),
        )

        if not enabled_configs:
            workflow.logger.debug("No teams with proactive tasks enabled")
            return {
                "teams_processed": 0,
                "teams_succeeded": 0,
                "teams_failed": 0,
                "total_signals_emitted": 0,
            }

        workflow.logger.debug(f"Processing {len(enabled_configs)} configs with proactive tasks enabled")

        # Track results
        total_signals_emitted = 0
        failed_teams: set[int] = set()
        successful_teams: set[int] = set()

        # Process configs in batches for controlled parallelism
        for batch_start in range(0, len(enabled_configs), DEFAULT_MAX_CONCURRENT_TEAMS):
            batch = enabled_configs[batch_start : batch_start + DEFAULT_MAX_CONCURRENT_TEAMS]

            # Start all workflows in batch concurrently
            workflow_handles: dict[
                int, ChildWorkflowHandle[VideoSegmentClusteringWorkflow, EmitSignalsResult | None]
            ] = {}
            for team_id, config_id in batch:
                try:
                    handle = await workflow.start_child_workflow(
                        VideoSegmentClusteringWorkflow.run,
                        ClusteringWorkflowInputs(
                            team_id=team_id,
                            lookback_hours=inputs.lookback_hours,
                        ),
                        id=clustering_workflow_id(team_id, config_id),
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                        # Clustering is fast, but priming session summaries takes a while due to video export.
                        # However, 3h should comfortably allow exporting even long sessions, thanks to optimization like
                        # ignoring inactivity or playback speedup. If this is not enough, then we need to optimize export further.
                        execution_timeout=timedelta(hours=3),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(seconds=30),
                            maximum_interval=timedelta(minutes=5),
                            backoff_coefficient=2.0,
                        ),
                        parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,  # Terminate but softly
                    )
                    workflow_handles[team_id] = handle
                except temporalio.exceptions.WorkflowAlreadyStartedError:
                    continue
                except Exception:
                    workflow.logger.exception(f"Failed to start video segment clustering for team {team_id}")
                    posthoganalytics.capture_exception(properties={"team_id": team_id})
                    failed_teams.add(team_id)

            # Wait for all workflows in batch to complete
            for team_id, handle in workflow_handles.items():
                try:
                    emit_result = await handle
                    if emit_result is not None:
                        total_signals_emitted += emit_result.signals_emitted
                    successful_teams.add(team_id)
                except Exception:
                    workflow.logger.exception(f"Video segment clustering errored for team {team_id}")
                    posthoganalytics.capture_exception(properties={"team_id": team_id})
                    failed_teams.add(team_id)

        return {
            "teams_processed": len(enabled_configs),
            "teams_succeeded": len(successful_teams),
            "teams_failed": len(failed_teams),
            "failed_team_ids": list(failed_teams),
            "total_signals_emitted": total_signals_emitted,
        }


@activity.defn
async def get_proactive_tasks_enabled_team_ids_activity() -> list[tuple[int, str]]:
    enabled_configs: list[tuple[int, str]] = []
    async for config in SignalSourceConfig.objects.filter(
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=True,
    ).only("team_id", "id"):
        enabled_configs.append((config.team_id, str(config.id)))
    return enabled_configs
