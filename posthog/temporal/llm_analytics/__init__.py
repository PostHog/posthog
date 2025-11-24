from posthog.temporal.llm_analytics.run_evaluation import (
    RunEvaluationWorkflow,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
)
from posthog.temporal.llm_analytics.trace_clustering import (
    DailyTraceClusteringWorkflow,
    TraceClusteringCoordinatorWorkflow,
    determine_optimal_k_activity,
    emit_cluster_events_activity,
    generate_cluster_labels_activity,
    get_teams_with_embeddings_activity,
    perform_clustering_activity,
    select_traces_for_clustering_activity,
)
from posthog.temporal.llm_analytics.trace_summarization import (
    BatchTraceSummarizationCoordinatorWorkflow,
    BatchTraceSummarizationWorkflow,
    embed_summaries_from_events_activity,
    generate_and_save_summary_activity,
    query_traces_in_window_activity,
)
from posthog.temporal.llm_analytics.trace_summarization.coordinator import get_teams_with_recent_traces_activity

WORKFLOWS = [
    RunEvaluationWorkflow,
    BatchTraceSummarizationWorkflow,
    BatchTraceSummarizationCoordinatorWorkflow,
    DailyTraceClusteringWorkflow,
    TraceClusteringCoordinatorWorkflow,
]

ACTIVITIES = [
    fetch_evaluation_activity,
    execute_llm_judge_activity,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
    query_traces_in_window_activity,
    generate_and_save_summary_activity,
    embed_summaries_from_events_activity,
    get_teams_with_recent_traces_activity,
    select_traces_for_clustering_activity,
    determine_optimal_k_activity,
    perform_clustering_activity,
    generate_cluster_labels_activity,
    emit_cluster_events_activity,
    get_teams_with_embeddings_activity,
]
