from posthog.temporal.llm_analytics.run_evaluation import (
    RunEvaluationWorkflow,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    update_key_state_activity,
)
from posthog.temporal.llm_analytics.trace_summarization import (
    BatchTraceSummarizationCoordinatorWorkflow,
    BatchTraceSummarizationWorkflow,
    embed_summaries_activity,
    generate_and_save_summary_activity,
    query_traces_in_window_activity,
)

WORKFLOWS = [
    RunEvaluationWorkflow,
    BatchTraceSummarizationWorkflow,
    BatchTraceSummarizationCoordinatorWorkflow,
]

ACTIVITIES = [
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    update_key_state_activity,
    execute_llm_judge_activity,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
    query_traces_in_window_activity,
    generate_and_save_summary_activity,
    embed_summaries_activity,
]
