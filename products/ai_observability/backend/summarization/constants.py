"""Configuration constants for AI observability summarization."""

from .models import OpenAIModel, SummarizationMode

# Default configuration
DEFAULT_MODEL_OPENAI = OpenAIModel.GPT_4_1_MINI
DEFAULT_MODE = SummarizationMode.MINIMAL

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 120

# Evaluation summary limits
EVALUATION_SUMMARY_MAX_RUNS = 250

# Large or verbose inputs are summarized as a bounded concurrent map-reduce so no
# individual ai-gateway request approaches its ~30s hard timeout.
EVALUATION_SUMMARY_CHUNK_SIZE = 20
EVALUATION_SUMMARY_MAP_PROMPT_MAX_CHARS = 20_000
EVALUATION_SUMMARY_MAP_REASONING_MAX_CHARS = 2_000
EVALUATION_SUMMARY_MAX_CONCURRENT_MAP_CALLS = 5
