from posthog.temporal.llm_analytics.run_evaluation import (
    RunEvaluationWorkflow,
    disable_evaluation_activity,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    update_key_state_activity,
)
from posthog.temporal.llm_analytics.trace_clustering import (
    DailyTraceClusteringWorkflow,
    TraceClusteringCoordinatorWorkflow,
    emit_cluster_events_activity,
    generate_cluster_labels_activity,
    perform_clustering_compute_activity,
)
from posthog.temporal.llm_analytics.trace_summarization import (
    BatchTraceSummarizationCoordinatorWorkflow,
    BatchTraceSummarizationWorkflow,
    generate_and_save_generation_summary_activity,
    generate_and_save_summary_activity,
    sample_items_in_window_activity,
)

EVAL_WORKFLOWS = [
    RunEvaluationWorkflow,
]

EVAL_ACTIVITIES = [
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    disable_evaluation_activity,
    update_key_state_activity,
    execute_llm_judge_activity,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
]

WORKFLOWS = [
    BatchTraceSummarizationWorkflow,
    BatchTraceSummarizationCoordinatorWorkflow,
    DailyTraceClusteringWorkflow,
    TraceClusteringCoordinatorWorkflow,
    # Keep eval workflow registered here temporarily so orphaned workflows on general-purpose queue can complete
    RunEvaluationWorkflow,
]

ACTIVITIES = [
    sample_items_in_window_activity,
    generate_and_save_summary_activity,
    generate_and_save_generation_summary_activity,
    # Clustering activities
    perform_clustering_compute_activity,
    generate_cluster_labels_activity,
    emit_cluster_events_activity,
    # Keep eval activities registered here temporarily so orphaned workflows on general-purpose queue can complete
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    disable_evaluation_activity,
    update_key_state_activity,
    execute_llm_judge_activity,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
]
