"""Data models for batch trace summarization."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_ITEMS_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_WINDOW_MINUTES,
)

from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import SummarizationMode, SummarizationProvider

# Analysis level determines whether we summarize traces or individual generations
AnalysisLevel = Literal["trace", "generation"]


class TraceSummary(BaseModel):
    """Summary result for a single trace"""

    trace_id: str
    text_repr: str
    summary: SummarizationResponse  # Use backend model directly for type safety
    metadata: dict[str, Any]


@dataclass
class BatchSummarizationInputs:
    """Inputs for batch trace summarization workflow.

    The workflow processes traces/generations from a time window (last N minutes) up to a maximum count.
    This makes it suitable for scheduled execution where each run processes recent items.
    """

    team_id: int
    analysis_level: AnalysisLevel = "trace"  # "trace" or "generation"
    max_items: int = DEFAULT_MAX_ITEMS_PER_WINDOW  # Hard limit on items to process
    batch_size: int = DEFAULT_BATCH_SIZE  # Number of items per batch
    mode: SummarizationMode = DEFAULT_MODE
    window_minutes: int = DEFAULT_WINDOW_MINUTES  # Time window to query (defaults to 60 min)
    provider: SummarizationProvider = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    # Optional explicit window (if not provided, uses window_minutes from now)
    window_start: str | None = None  # RFC3339 format
    window_end: str | None = None  # RFC3339 format


@dataclass
class SampledItem:
    """A sampled item for summarization.

    Used by both trace-level and generation-level sampling to provide
    consistent data structure with trace context.
    """

    trace_id: str  # The trace ID
    trace_first_timestamp: str  # First event timestamp of the trace (for navigation)
    generation_id: str | None = None  # Generation UUID (None for trace-level, set for generation-level)


@dataclass
class SummarizationActivityResult:
    """Result from generate_and_save_summary_activity."""

    trace_id: str  # Always set - the trace ID (or parent trace for generations)
    success: bool
    generation_id: str | None = None  # Only set for generation-level summarization
    text_repr_length: int = 0
    event_count: int = 0
    skipped: bool = False
    skip_reason: str | None = None
    embedding_requested: bool = False
    embedding_request_error: str | None = None


@dataclass
class BatchSummarizationMetrics:
    """Metrics from batch summarization workflow."""

    items_queried: int = 0  # traces or generations depending on analysis_level
    summaries_skipped: int = 0
    summaries_failed: int = 0
    summaries_generated: int = 0
    embedding_requests_succeeded: int = 0
    embedding_requests_failed: int = 0
    duration_seconds: float = 0.0


@dataclass
class BatchSummarizationResult:
    """Results from batch trace summarization workflow."""

    batch_run_id: str
    metrics: BatchSummarizationMetrics


@dataclass
class CoordinatorResult:
    """Results from coordinator workflow."""

    teams_processed: int
    teams_failed: int
    failed_team_ids: list[int]
    total_items: int  # traces or generations depending on analysis_level
    total_summaries: int
