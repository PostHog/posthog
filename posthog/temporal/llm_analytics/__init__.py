from posthog.temporal.llm_analytics.run_evaluation import (
    RunEvaluationWorkflow,
    emit_evaluation_event_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
)
from posthog.temporal.llm_analytics.trace_summarization import (
    BatchTraceSummarizationCoordinatorWorkflow,
    BatchTraceSummarizationWorkflow,
    emit_trace_summary_events_activity,
    fetch_trace_hierarchy_activity,
    generate_summary_activity,
    query_traces_in_window_activity,
)
from posthog.temporal.llm_analytics.trace_summarization.coordinator import get_teams_with_recent_traces_activity

WORKFLOWS = [
    RunEvaluationWorkflow,
    BatchTraceSummarizationWorkflow,
    BatchTraceSummarizationCoordinatorWorkflow,
]

ACTIVITIES = [
    fetch_evaluation_activity,
    execute_llm_judge_activity,
    emit_evaluation_event_activity,
    query_traces_in_window_activity,
    fetch_trace_hierarchy_activity,
    generate_summary_activity,
    emit_trace_summary_events_activity,
    get_teams_with_recent_traces_activity,
]
