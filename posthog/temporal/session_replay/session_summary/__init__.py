from posthog.temporal.session_replay.session_summary.activities import (
    analyze_video_segment_activity,
    capture_timing_activity,
    cleanup_gemini_file_activity,
    consolidate_video_segments_activity,
    embed_and_store_segments_activity,
    prep_session_video_asset_activity,
    store_video_session_summary_activity,
    tag_and_highlight_session_activity,
    upload_video_to_gemini_activity,
)
from posthog.temporal.session_replay.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
)
from posthog.temporal.session_replay.session_summary.activities.video_validation import (
    validate_llm_single_session_summary_with_videos_activity,
)
from posthog.temporal.session_replay.session_summary.summarize_session import (
    SummarizeSingleSessionStreamWorkflow,
    SummarizeSingleSessionWorkflow,
    fetch_session_data_activity,
    get_llm_single_session_summary_activity,
    stream_llm_single_session_summary_activity,
)
from posthog.temporal.session_replay.session_summary.summarize_session_group import (
    SummarizeSessionGroupWorkflow,
    fetch_session_batch_events_activity,
)

SESSION_SUMMARY_WORKFLOWS = [
    SummarizeSingleSessionStreamWorkflow,
    SummarizeSingleSessionWorkflow,
    SummarizeSessionGroupWorkflow,
]

SESSION_SUMMARY_ACTIVITIES = [
    stream_llm_single_session_summary_activity,
    get_llm_single_session_summary_activity,
    fetch_session_batch_events_activity,
    extract_session_group_patterns_activity,
    assign_events_to_patterns_activity,
    fetch_session_data_activity,
    combine_patterns_from_chunks_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
    validate_llm_single_session_summary_with_videos_activity,
    prep_session_video_asset_activity,
    upload_video_to_gemini_activity,
    analyze_video_segment_activity,
    embed_and_store_segments_activity,
    store_video_session_summary_activity,
    tag_and_highlight_session_activity,
    cleanup_gemini_file_activity,
    consolidate_video_segments_activity,
    capture_timing_activity,
]
