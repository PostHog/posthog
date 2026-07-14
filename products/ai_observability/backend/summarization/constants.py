"""Configuration constants for AI observability summarization."""

from .models import OpenAIModel, SummarizationMode

# Default configuration
DEFAULT_MODEL_OPENAI = OpenAIModel.GPT_4_1_MINI
DEFAULT_MODE = SummarizationMode.MINIMAL

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 120

# Evaluation summary limits
EVALUATION_SUMMARY_MAX_RUNS = 250

# Runs above this count are summarized as a concurrent map-reduce instead of one big
# LLM call. A single call over all 250 runs takes long enough (20-30s+) to routinely
# trip the internal ai-gateway's ~30s hard timeout; splitting keeps every individual
# call well under the cliff so the request reliably completes.
EVALUATION_SUMMARY_CHUNK_SIZE = 50
