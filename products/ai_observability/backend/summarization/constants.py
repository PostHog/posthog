"""Configuration constants for AI observability summarization."""

from .models import OpenAIModel, SummarizationMode

# Default configuration
DEFAULT_MODEL_OPENAI = OpenAIModel.GPT_4_1_MINI
DEFAULT_MODE = SummarizationMode.MINIMAL

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 120
# Flex requests queue for spare provider capacity, so they get a longer deadline. It must stay
# under the ai-gateway's non-streaming response ceiling (~290s): past that the gateway answers
# with a status error instead of a client timeout, and the caller's standard-tier retry never runs.
SUMMARIZATION_FLEX_TIMEOUT = 180
