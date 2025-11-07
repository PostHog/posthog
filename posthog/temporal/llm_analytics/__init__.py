from posthog.temporal.llm_analytics.run_evaluation import (
    RunEvaluationWorkflow,
    emit_evaluation_event_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
    fetch_target_event_activity,
)

WORKFLOWS = [
    RunEvaluationWorkflow,
]

ACTIVITIES = [
    fetch_target_event_activity,
    fetch_evaluation_activity,
    execute_llm_judge_activity,
    emit_evaluation_event_activity,
]
