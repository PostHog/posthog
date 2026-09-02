"""Type definitions for AI observability summarization."""

from enum import StrEnum


class OpenAIModel(StrEnum):
    """Supported OpenAI models for summarization."""

    GPT_4_1_NANO = "gpt-4.1-nano"
    GPT_4_1_MINI = "gpt-4.1-mini"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"
    GPT_5_MINI = "gpt-5-mini"

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
