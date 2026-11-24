from typing import TYPE_CHECKING

from .eval_suggestions import (
    ACTIVITIES as EVAL_SUGGESTIONS_ACTIVITIES,
    WORKFLOWS as EVAL_SUGGESTIONS_WORKFLOWS,
)
from .trace_summary import TraceSummaryWorkflow, fail_trace_summary_activity, generate_trace_summary_activity

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [TraceSummaryWorkflow, *EVAL_SUGGESTIONS_WORKFLOWS]
ACTIVITIES: list[ActivityDefinition] = [
    generate_trace_summary_activity,
    fail_trace_summary_activity,
    *EVAL_SUGGESTIONS_ACTIVITIES,
]
