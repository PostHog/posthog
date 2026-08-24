"""Configuration constants for AI observability summarization."""

from .models import OpenAIModel, SummarizationMode

# Default configuration
DEFAULT_MODEL_OPENAI = OpenAIModel.GPT_4_1_MINI
DEFAULT_MODE = SummarizationMode.MINIMAL

# The formatters' 2M default overflows the default model's 1,048,576-token window, because trace
# JSON runs about 1.6 chars per token rather than the ~4 of prose.
MAX_TEXT_REPR_CHARS = 1_000_000

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 120
