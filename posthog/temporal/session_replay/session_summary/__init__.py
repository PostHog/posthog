from posthog.temporal.session_replay.session_summary.activities.capture_timing import capture_timing_activity
from posthog.temporal.session_replay.session_summary.activities.check_summary_exists import (
    check_summary_exists_activity,
)
from posthog.temporal.session_replay.session_summary.activities.event_based import (
    fetch_session_data_activity,
    get_llm_single_session_summary_activity,
)
from posthog.temporal.session_replay.session_summary.activities.video_based import (
    analyze_video_segment_activity,
    cleanup_gemini_file_activity,
    consolidate_video_segments_activity,
    embed_and_store_segments_activity,
    emit_session_problem_signals_activity,
    prep_session_video_asset_activity,
    slice_session_data_for_segments_activity,
    store_video_session_summary_activity,
    tag_and_highlight_session_activity,
    upload_video_to_gemini_activity,
)
from posthog.temporal.session_replay.session_summary.workflow import SummarizeSingleSessionWorkflow

SESSION_SUMMARY_WORKFLOWS = [
    SummarizeSingleSessionWorkflow,
]

SESSION_SUMMARY_ACTIVITIES = [
    check_summary_exists_activity,
    fetch_session_data_activity,
    get_llm_single_session_summary_activity,
    prep_session_video_asset_activity,
    upload_video_to_gemini_activity,
    slice_session_data_for_segments_activity,
    analyze_video_segment_activity,
    consolidate_video_segments_activity,
    embed_and_store_segments_activity,
    emit_session_problem_signals_activity,
    store_video_session_summary_activity,
    tag_and_highlight_session_activity,
    cleanup_gemini_file_activity,
    capture_timing_activity,
]
