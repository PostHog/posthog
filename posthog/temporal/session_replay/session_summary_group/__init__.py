from posthog.temporal.session_replay.session_summary_group.activities import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    fetch_session_batch_events_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
)
from posthog.temporal.session_replay.session_summary_group.workflow import SummarizeSessionGroupWorkflow

SESSION_SUMMARY_GROUP_WORKFLOWS = [SummarizeSessionGroupWorkflow]

SESSION_SUMMARY_GROUP_ACTIVITIES = [
    fetch_session_batch_events_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
    extract_session_group_patterns_activity,
    combine_patterns_from_chunks_activity,
    assign_events_to_patterns_activity,
]
