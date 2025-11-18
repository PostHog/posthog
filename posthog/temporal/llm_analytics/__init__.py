from posthog.temporal.llm_analytics.run_evaluation import (
    RunEvaluationWorkflow,
    emit_evaluation_event_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
)
from posthog.temporal.llm_analytics.trace_summarization import (
    BatchTraceSummarizationWorkflow,
    emit_trace_summary_events_activity,
    fetch_trace_hierarchy_activity,
    generate_summary_activity,
    query_traces_in_window_activity,
)

WORKFLOWS = [
    RunEvaluationWorkflow,
    BatchTraceSummarizationWorkflow,
]

ACTIVITIES = [
    fetch_evaluation_activity,
    execute_llm_judge_activity,
    emit_evaluation_event_activity,
    query_traces_in_window_activity,
    fetch_trace_hierarchy_activity,
    generate_summary_activity,
    emit_trace_summary_events_activity,
]
