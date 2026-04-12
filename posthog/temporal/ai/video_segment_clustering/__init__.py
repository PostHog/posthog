"""
This module automatically identifies recurring issues from session replay video analysis by clustering similar
session segments and creating Tasks from actionable clusters for engineering teams to investigate/solve.

Session replays are analyzed by AI to generate natural language descriptions of what users are doing in each
video segment. These descriptions are embedded as vectors and stored in ClickHouse.
This workflow periodically processes those embeddings to find patterns - if multiple users encounter the same issue
(e.g., "User clicked submit button repeatedly but nothing happened"), those segments cluster together
and become a Task for the team to fix.
"""

from posthog.temporal.ai.video_segment_clustering.activities import (
    cluster_segments_activity,
    emit_signals_from_clusters_activity,
    fetch_segments_activity,
    get_sessions_to_prime_activity,
)
from posthog.temporal.ai.video_segment_clustering.clustering_workflow import VideoSegmentClusteringWorkflow
from posthog.temporal.ai.video_segment_clustering.coordinator_workflow import (
    VideoSegmentClusteringCoordinatorWorkflow,
    get_proactive_tasks_enabled_team_ids_activity,
)

VIDEO_SEGMENT_CLUSTERING_WORKFLOWS = [
    VideoSegmentClusteringWorkflow,
    VideoSegmentClusteringCoordinatorWorkflow,
]

VIDEO_SEGMENT_CLUSTERING_ACTIVITIES = [
    get_sessions_to_prime_activity,
    fetch_segments_activity,
    cluster_segments_activity,
    emit_signals_from_clusters_activity,
    get_proactive_tasks_enabled_team_ids_activity,
]
