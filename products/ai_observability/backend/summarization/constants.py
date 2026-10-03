"""Configuration constants for AI observability summarization."""

from .models import OpenAIModel, SummarizationMode

# Default configuration
DEFAULT_MODEL_OPENAI = OpenAIModel.GPT_4_1_MINI
DEFAULT_MODE = SummarizationMode.MINIMAL

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 120
# Flex requests queue for spare provider capacity, so they get a longer deadline. It must stay
# under the ai-gateway's buffered-response ceiling: the gateway cuts a non-streaming call at
# ~290s and answers 504 (DefaultBufferedHeaderTimeout in ai-gateway internal/dispatch/proxy),
# which the SDK raises as InternalServerError, so the standard-tier fallback still runs.
SUMMARIZATION_FLEX_TIMEOUT = 180
