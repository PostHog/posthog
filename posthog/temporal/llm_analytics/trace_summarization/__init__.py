"""Trace summarization workflows and activities for batch processing."""

# Export activities
# Export constants
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TRACES_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_WINDOW_MINUTES,
    EVENT_NAME_TRACE_SUMMARY,
    WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.trace_summarization.coordinator import (
    BatchTraceSummarizationCoordinatorInputs,
    BatchTraceSummarizationCoordinatorWorkflow,
)

# Export models
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs
from posthog.temporal.llm_analytics.trace_summarization.sampling import query_traces_in_window_activity
from posthog.temporal.llm_analytics.trace_summarization.schedule import create_batch_trace_summarization_schedule
from posthog.temporal.llm_analytics.trace_summarization.summarization import generate_and_save_summary_activity

# Export workflows
from posthog.temporal.llm_analytics.trace_summarization.workflow import BatchTraceSummarizationWorkflow

__all__ = [
    # Activities
    "generate_and_save_summary_activity",
    "query_traces_in_window_activity",
    # Constants
    "COORDINATOR_WORKFLOW_NAME",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MAX_TRACES_PER_WINDOW",
    "DEFAULT_MODE",
    "DEFAULT_WINDOW_MINUTES",
    "EVENT_NAME_TRACE_SUMMARY",
    "WORKFLOW_NAME",
    # Models
    "BatchSummarizationInputs",
    "BatchTraceSummarizationCoordinatorInputs",
    # Workflows
    "BatchTraceSummarizationWorkflow",
    "BatchTraceSummarizationCoordinatorWorkflow",
    # Schedule
    "create_batch_trace_summarization_schedule",
]
