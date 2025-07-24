from posthog.temporal.ai.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from .sync_vectors import (
    SyncVectorsInputs,
    SyncVectorsWorkflow,
    batch_embed_and_sync_actions,
    batch_summarize_actions,
    get_approximate_actions_count,
)

from .session_summary.summarize_session import (
    SummarizeSingleSessionWorkflow,
    stream_llm_single_session_summary_activity,
    fetch_session_data_activity,
)

from .session_summary.summarize_session_group import (
    SummarizeSessionGroupWorkflow,
    SessionGroupSummaryInputs,
    SessionGroupSummaryOfSummariesInputs,
    get_llm_single_session_summary_activity,
    fetch_session_batch_events_activity,
)

from posthog.temporal.ai.conversation import (
    AssistantConversationRunnerWorkflow,
    process_conversation_activity,
)

WORKFLOWS = [
    SyncVectorsWorkflow,
    SummarizeSingleSessionWorkflow,
    SummarizeSessionGroupWorkflow,
    AssistantConversationRunnerWorkflow,
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
    split_session_summaries_into_chunks_for_patterns_extraction_activity
]

__all__ = [
    "SyncVectorsInputs",
    "SingleSessionSummaryInputs",
    "SessionGroupSummaryInputs",
    "SessionGroupSummaryOfSummariesInputs",
]
