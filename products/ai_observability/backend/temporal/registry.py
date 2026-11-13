from .eval_suggestions import (
    ACTIVITIES as EVAL_SUGGESTIONS_ACTIVITIES,
    WORKFLOWS as EVAL_SUGGESTIONS_WORKFLOWS,
)
from .clustering import (
    ACTIVITIES as CLUSTERING_ACTIVITIES,
    WORKFLOWS as CLUSTERING_WORKFLOWS,
)
from .trace_summary import TraceSummaryWorkflow, fail_trace_summary_activity, generate_trace_summary_activity

WORKFLOWS = [TraceSummaryWorkflow, *EVAL_SUGGESTIONS_WORKFLOWS, *CLUSTERING_WORKFLOWS]
ACTIVITIES = [
    generate_trace_summary_activity,
    fail_trace_summary_activity,
    *EVAL_SUGGESTIONS_ACTIVITIES,
    *CLUSTERING_ACTIVITIES,
]
