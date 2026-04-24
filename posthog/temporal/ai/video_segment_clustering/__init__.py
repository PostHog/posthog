"""
Session replay: scheduled video summary runs for teams with session analysis signals enabled.

The per-team workflow lists sessions missing a video summary and runs `summarize-session`
for each (priming). Session problem signals are emitted inside that workflow
(emit_session_problem_signals_activity).
"""

from posthog.temporal.ai.video_segment_clustering.clustering_activities import get_sessions_to_prime_activity
from posthog.temporal.ai.video_segment_clustering.clustering_workflow import VideoSegmentClusteringWorkflow
from posthog.temporal.ai.video_segment_clustering.coordinator_activities import (
    list_teams_with_session_analysis_signals_activity,
)
from posthog.temporal.ai.video_segment_clustering.coordinator_workflow import VideoSegmentClusteringCoordinatorWorkflow

VIDEO_SEGMENT_CLUSTERING_WORKFLOWS = [
    VideoSegmentClusteringWorkflow,
    VideoSegmentClusteringCoordinatorWorkflow,
]

VIDEO_SEGMENT_CLUSTERING_ACTIVITIES = [
    get_sessions_to_prime_activity,
    list_teams_with_session_analysis_signals_activity,
]
