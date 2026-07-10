from posthog.temporal.ai_observability.eval_reports.activities import (
    check_count_triggered_eval_report_activity,
    deliver_report_activity,
    fetch_count_triggered_eval_report_candidates_activity,
    fetch_due_eval_reports_activity,
    prepare_report_context_activity,
    run_eval_report_agent_activity,
    store_report_run_activity,
    update_next_delivery_date_activity,
)
from posthog.temporal.ai_observability.eval_reports.emit_signal import (
    EmitEvalReportSignalWorkflow,
    emit_eval_report_signal_activity,
)
from posthog.temporal.ai_observability.eval_reports.workflow import (
    CheckCountTriggeredReportsWorkflow,
    GenerateAndDeliverEvalReportWorkflow,
    ScheduleAllEvalReportsWorkflow,
)
from posthog.temporal.ai_observability.evaluation_clustering import (
    AIObservabilityEvaluationClusteringCoordinatorWorkflow,
    AIObservabilityEvaluationClusteringWorkflow,
    AIObservabilityEvaluationSamplerCoordinatorWorkflow,
    AIObservabilityEvaluationSamplerWorkflow,
    compute_evaluation_cluster_aggregates_activity,
    emit_evaluation_cluster_events_activity,
    fetch_evaluation_metadata_activity,
    generate_evaluation_cluster_labels_activity,
    perform_evaluation_clustering_compute_activity,
    sample_and_embed_for_job_activity,
)
from posthog.temporal.ai_observability.evaluation_hog import execute_hog_eval_activity
from posthog.temporal.ai_observability.evaluation_llm_judge import execute_llm_judge_activity
from posthog.temporal.ai_observability.evaluation_sentiment import execute_sentiment_eval_activity
from posthog.temporal.ai_observability.evaluation_workflow_activities import (
    disable_evaluation_activity,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    send_evaluation_disabled_email_activity,
    send_trial_usage_email_activity,
    update_key_state_activity,
)
from posthog.temporal.ai_observability.metrics import EvalsMetricsInterceptor  # noqa: F401
from posthog.temporal.ai_observability.run_evaluation import RunEvaluationWorkflow
from posthog.temporal.ai_observability.run_tagger import (
    RunTaggerWorkflow,
    disable_tagger_activity,
    emit_tagger_event_activity,
    execute_hog_tagger_activity,
    execute_tagger_activity,
    fetch_tagger_activity,
)
from posthog.temporal.ai_observability.run_trace_evaluation import (
    RunTraceEvaluationWorkflow,
    emit_trace_evaluation_event_activity,
    execute_trace_hog_eval_activity,
    execute_trace_llm_judge_activity,
)
from posthog.temporal.ai_observability.shared_activities import (
    fetch_all_clustering_filters_activity,
    fetch_all_clustering_jobs_activity,
)
from posthog.temporal.ai_observability.team_discovery import get_team_ids_for_ai_observability
from posthog.temporal.ai_observability.trace_clustering import (
    DailyTraceClusteringWorkflow,
    TraceClusteringCoordinatorWorkflow,
    compute_cluster_aggregates_activity,
    emit_cluster_events_activity,
    generate_cluster_labels_activity,
    perform_clustering_compute_activity,
)
from posthog.temporal.ai_observability.trace_summarization import (
    BatchTraceSummarizationCoordinatorWorkflow,
    BatchTraceSummarizationWorkflow,
    fetch_and_format_activity,
    sample_items_in_window_activity,
    summarize_and_save_activity,
)

from products.signals.backend.temporal.emit_eval_signal import emit_eval_signal_activity

EVAL_WORKFLOWS = [
    RunEvaluationWorkflow,
    RunTraceEvaluationWorkflow,
]

EVAL_ACTIVITIES = [
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    disable_evaluation_activity,
    send_trial_usage_email_activity,
    send_evaluation_disabled_email_activity,
    update_key_state_activity,
    execute_llm_judge_activity,
    execute_hog_eval_activity,
    execute_sentiment_eval_activity,
    execute_trace_llm_judge_activity,
    execute_trace_hog_eval_activity,
    emit_evaluation_event_activity,
    emit_trace_evaluation_event_activity,
    emit_internal_telemetry_activity,
    emit_eval_signal_activity,  # kept for in-flight v1 workflows, then remove
]

TAGGER_WORKFLOWS = [
    RunTaggerWorkflow,
]

TAGGER_ACTIVITIES = [
    fetch_tagger_activity,
    execute_tagger_activity,
    execute_hog_tagger_activity,
    emit_tagger_event_activity,
    disable_tagger_activity,
]

WORKFLOWS = [
    BatchTraceSummarizationWorkflow,
    BatchTraceSummarizationCoordinatorWorkflow,
    DailyTraceClusteringWorkflow,
    TraceClusteringCoordinatorWorkflow,
    # Evaluation reports
    ScheduleAllEvalReportsWorkflow,
    CheckCountTriggeredReportsWorkflow,
    GenerateAndDeliverEvalReportWorkflow,
    EmitEvalReportSignalWorkflow,
    # Evaluation clustering (Stage A sampler + Stage B clustering)
    AIObservabilityEvaluationSamplerCoordinatorWorkflow,
    AIObservabilityEvaluationSamplerWorkflow,
    AIObservabilityEvaluationClusteringCoordinatorWorkflow,
    AIObservabilityEvaluationClusteringWorkflow,
    # Keep eval workflow registered here temporarily so orphaned workflows on general-purpose queue can complete
    RunEvaluationWorkflow,
]

ACTIVITIES = [
    # Team discovery
    get_team_ids_for_ai_observability,
    # Summarization activities
    sample_items_in_window_activity,
    fetch_and_format_activity,
    summarize_and_save_activity,
    # Shared activities
    fetch_all_clustering_filters_activity,
    fetch_all_clustering_jobs_activity,
    # Clustering activities
    perform_clustering_compute_activity,
    generate_cluster_labels_activity,
    compute_cluster_aggregates_activity,
    emit_cluster_events_activity,
    # Evaluation report activities
    fetch_due_eval_reports_activity,
    fetch_count_triggered_eval_report_candidates_activity,
    check_count_triggered_eval_report_activity,
    prepare_report_context_activity,
    run_eval_report_agent_activity,
    store_report_run_activity,
    deliver_report_activity,
    update_next_delivery_date_activity,
    emit_eval_report_signal_activity,
    # Evaluation clustering activities
    sample_and_embed_for_job_activity,
    perform_evaluation_clustering_compute_activity,
    fetch_evaluation_metadata_activity,
    generate_evaluation_cluster_labels_activity,
    compute_evaluation_cluster_aggregates_activity,
    emit_evaluation_cluster_events_activity,
    # Keep eval activities registered here temporarily so orphaned workflows on general-purpose queue can complete
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    disable_evaluation_activity,
    send_trial_usage_email_activity,
    send_evaluation_disabled_email_activity,
    update_key_state_activity,
    execute_llm_judge_activity,
    execute_hog_eval_activity,
    execute_sentiment_eval_activity,
    emit_evaluation_event_activity,
    emit_internal_telemetry_activity,
    emit_eval_signal_activity,  # kept for in-flight v1 workflows, then remove
]
