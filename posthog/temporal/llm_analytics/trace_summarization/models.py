"""Data models for batch trace summarization."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODE,
    DEFAULT_SAMPLE_SIZE,
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
    team_id: int
    sample_size: int = DEFAULT_SAMPLE_SIZE
    batch_size: int = DEFAULT_BATCH_SIZE
    mode: str = DEFAULT_MODE
    start_date: str | None = None  # RFC3339 format
    end_date: str | None = None  # RFC3339 format
