from posthog.temporal.ai.conversation import AssistantConversationRunnerWorkflow, process_conversation_activity
from posthog.temporal.ai.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

# Import LLM analytics workflows - placed in posthog.temporal.ai since they share the MAX_AI_TASK_QUEUE
from posthog.temporal.llm_analytics.run_evaluation import (
    RunEvaluationWorkflow,
    emit_evaluation_event_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
    fetch_target_event_activity,
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

WORKFLOWS = [
    SyncVectorsWorkflow,
    SummarizeSingleSessionStreamWorkflow,
    SummarizeSingleSessionWorkflow,
    SummarizeSessionGroupWorkflow,
    AssistantConversationRunnerWorkflow,
    RunEvaluationWorkflow,
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
    fetch_target_event_activity,
    fetch_evaluation_activity,
    execute_llm_judge_activity,
    emit_evaluation_event_activity,
]

__all__ = [
    "SyncVectorsInputs",
    "SingleSessionSummaryInputs",
    "SessionGroupSummaryInputs",
    "SessionGroupSummaryOfSummariesInputs",
]
