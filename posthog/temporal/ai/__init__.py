from posthog.temporal.ai.chat_agent import (
    AssistantConversationRunnerWorkflow,
    ChatAgentWorkflow,
    process_chat_agent_activity,
    process_conversation_activity,
)
from posthog.temporal.ai.research_agent import ResearchAgentWorkflow, process_research_agent_activity
from posthog.temporal.ai.session_summary.activities import (
    analyze_video_segment_activity,
    capture_timing_activity,
    consolidate_video_segments_activity,
    embed_and_store_segments_activity,
    prep_session_video_asset_activity,
    store_video_session_summary_activity,
    upload_video_to_gemini_activity,
)
from posthog.temporal.ai.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
)
from posthog.temporal.ai.session_summary.activities.video_validation import (
    validate_llm_single_session_summary_with_videos_activity,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.ai.slack_conversation import (
    SlackConversationRunnerWorkflow,
    SlackConversationRunnerWorkflowInputs,
    process_slack_conversation_activity,
)

from .llm_traces_summaries.summarize_traces import (
    SummarizeLLMTracesInputs,
    SummarizeLLMTracesWorkflow,
    summarize_llm_traces_activity,
)
from .session_summary.summarize_session import (
    SummarizeSingleSessionStreamWorkflow,
    SummarizeSingleSessionWorkflow,
    fetch_session_data_activity,
    get_llm_single_session_summary_activity,
    stream_llm_single_session_summary_activity,
)
from .session_summary.summarize_session_group import (
    SessionGroupSummaryInputs,
    SessionGroupSummaryOfSummariesInputs,
    SummarizeSessionGroupWorkflow,
    fetch_session_batch_events_activity,
)
from .sync_vectors import (
    SyncVectorsInputs,
    SyncVectorsWorkflow,
    batch_embed_and_sync_actions,
    batch_summarize_actions,
    get_approximate_actions_count,
)
from .video_segment_clustering.activities import (
    cluster_segments_activity,
    fetch_segments_activity,
    get_sessions_to_prime_activity,
    label_clusters_activity,
    match_clusters_activity,
    persist_reports_activity,
)
from .video_segment_clustering.clustering_workflow import VideoSegmentClusteringWorkflow
from .video_segment_clustering.coordinator_workflow import (
    VideoSegmentClusteringCoordinatorWorkflow,
    get_proactive_tasks_enabled_team_ids_activity,
)

WORKFLOWS = [
    SyncVectorsWorkflow,
    SummarizeSingleSessionStreamWorkflow,
    SummarizeSingleSessionWorkflow,
    SummarizeSessionGroupWorkflow,
    AssistantConversationRunnerWorkflow,
    ChatAgentWorkflow,
    ResearchAgentWorkflow,
    SummarizeLLMTracesWorkflow,
    SlackConversationRunnerWorkflow,
    # Video segment clustering workflows
    VideoSegmentClusteringWorkflow,
    VideoSegmentClusteringCoordinatorWorkflow,
]

ACTIVITIES = [
    get_approximate_actions_count,
    batch_summarize_actions,
    batch_embed_and_sync_actions,
    stream_llm_single_session_summary_activity,
    get_llm_single_session_summary_activity,
    fetch_session_batch_events_activity,
    extract_session_group_patterns_activity,
    assign_events_to_patterns_activity,
    fetch_session_data_activity,
    combine_patterns_from_chunks_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
    process_conversation_activity,
    process_chat_agent_activity,
    process_research_agent_activity,
    validate_llm_single_session_summary_with_videos_activity,
    summarize_llm_traces_activity,
    process_slack_conversation_activity,
    # Video analysis activities
    prep_session_video_asset_activity,
    upload_video_to_gemini_activity,
    analyze_video_segment_activity,
    embed_and_store_segments_activity,
    store_video_session_summary_activity,
    consolidate_video_segments_activity,
    capture_timing_activity,
    # Video segment clustering activities
    get_sessions_to_prime_activity,
    fetch_segments_activity,
    cluster_segments_activity,
    match_clusters_activity,
    label_clusters_activity,
    persist_reports_activity,
    get_proactive_tasks_enabled_team_ids_activity,
]

__all__ = [
    "SyncVectorsInputs",
    "SingleSessionSummaryInputs",
    "SessionGroupSummaryInputs",
    "SessionGroupSummaryOfSummariesInputs",
    "SummarizeLLMTracesInputs",
    "SlackConversationRunnerWorkflowInputs",
]
