"""Data models for batch trace summarization."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TRACES_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_WINDOW_MINUTES,
)

from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse


class TraceSummary(BaseModel):
    """Summary result for a single trace"""

    trace_id: str
    text_repr: str
    summary: SummarizationResponse  # Use backend model directly for type safety
    metadata: dict[str, Any]


@dataclass
class BatchSummarizationInputs:
    """Inputs for batch trace summarization workflow.

    The workflow processes traces from a time window (last N minutes) up to a maximum count.
    This makes it suitable for scheduled execution where each run processes recent traces.
    """

    team_id: int
    max_traces: int = DEFAULT_MAX_TRACES_PER_WINDOW  # Hard limit on traces to process
    batch_size: int = DEFAULT_BATCH_SIZE  # Number of traces per batch
    mode: str = DEFAULT_MODE  # 'minimal' or 'comprehensive'
    window_minutes: int = DEFAULT_WINDOW_MINUTES  # Time window to query (defaults to 60 min)
    # Optional explicit window (if not provided, uses window_minutes from now)
    window_start: str | None = None  # RFC3339 format
    window_end: str | None = None  # RFC3339 format
