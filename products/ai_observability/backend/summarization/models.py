"""Type definitions for AI observability summarization."""

from enum import StrEnum
from typing import Literal

from posthog.dataclasses import frozen


class OpenAIModel(StrEnum):
    """Supported OpenAI models for summarization."""

    GPT_4_1_NANO = "gpt-4.1-nano"
    GPT_4_1_MINI = "gpt-4.1-mini"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"
    GPT_5_MINI = "gpt-5-mini"
    GPT_5_NANO = "gpt-5-nano"

    @classmethod
    def parse(cls, value: str) -> "OpenAIModel":
        """Parse a model id, raising a ValueError that names the accepted values."""
        try:
            return cls(value)
        except ValueError:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(f"Unknown summarization model {value!r}. Valid models: {valid}") from None


class SummarizationMode(StrEnum):
    """Summary detail levels."""

    MINIMAL = "minimal"
    DETAILED = "detailed"

    @classmethod
    def parse(cls, value: str) -> "SummarizationMode":
        """Parse a mode, raising a ValueError that names the accepted values."""
        try:
            return cls(value)
        except ValueError:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(f"Unknown summarization mode {value!r}. Valid modes: {valid}") from None


@frozen
class SummarizationCallContext:
    """Labels that link one summarization call to its log line, captured exception and gateway event."""

    source: Literal["api", "batch", "posthog_ai"]
    trace_id: str | None = None
    generation_id: str | None = None
    temporal_activity_id: str | None = None
    temporal_attempt: int | None = None
    # False while Temporal still has a retry left for the activity, so a failure does not lose the summary yet.
    final_attempt: bool = True

    def as_properties(self) -> dict[str, str | int | bool]:
        properties: dict[str, str | int | bool | None] = {
            "summarization_source": self.source,
            "summarized_trace_id": self.trace_id,
            "summarized_generation_id": self.generation_id,
            "temporal_activity_id": self.temporal_activity_id,
            "temporal_attempt": self.temporal_attempt,
            "final_attempt": self.final_attempt,
        }
        return {key: value for key, value in properties.items() if value is not None}
