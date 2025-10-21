from posthog.temporal.ai.conversation import AssistantConversationRunnerWorkflow, process_conversation_activity
from posthog.temporal.ai.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

from .entity_configs import ActionEntityConfig, CohortEntityConfig
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
from .sync_cohort_vectors import (
    SyncCohortVectorsInputs,
    SyncCohortVectorsWorkflow,
    batch_embed_and_sync_cohorts,
    batch_summarize_cohorts,
    get_approximate_cohorts_count,
)
from .sync_entity_vectors import (
    SyncEntityVectorsInputs,
    SyncEntityVectorsWorkflow,
    batch_embed_and_sync_entities,
    batch_summarize_entities,
    get_approximate_entities_count,
    register_entity_config,
)
from .sync_vectors import (
    SyncVectorsInputs,
    SyncVectorsWorkflow,
    batch_embed_and_sync_actions,
    batch_summarize_actions,
    get_approximate_actions_count,
)

# Register entity configurations
register_entity_config(ActionEntityConfig())
register_entity_config(CohortEntityConfig())

WORKFLOWS = [
    SyncVectorsWorkflow,
    SyncCohortVectorsWorkflow,
    SyncEntityVectorsWorkflow,
    SummarizeSingleSessionStreamWorkflow,
    SummarizeSingleSessionWorkflow,
    SummarizeSessionGroupWorkflow,
    AssistantConversationRunnerWorkflow,
]

ACTIVITIES = [
    get_approximate_actions_count,
    batch_summarize_actions,
    batch_embed_and_sync_actions,
    get_approximate_cohorts_count,
    batch_summarize_cohorts,
    batch_embed_and_sync_cohorts,
    get_approximate_entities_count,
    batch_summarize_entities,
    batch_embed_and_sync_entities,
    stream_llm_single_session_summary_activity,
    get_llm_single_session_summary_activity,
    fetch_session_batch_events_activity,
    extract_session_group_patterns_activity,
    assign_events_to_patterns_activity,
    fetch_session_data_activity,
    combine_patterns_from_chunks_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
    process_conversation_activity,
]

__all__ = [
    "SyncVectorsInputs",
    "SyncCohortVectorsInputs",
    "SyncEntityVectorsInputs",
    "SingleSessionSummaryInputs",
    "SessionGroupSummaryInputs",
    "SessionGroupSummaryOfSummariesInputs",
]
