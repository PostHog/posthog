"""Configuration constants for AI observability summarization."""

from .models import OpenAIModel, SummarizationMode

# Default configuration
DEFAULT_MODEL_OPENAI = OpenAIModel.GPT_4_1_MINI
DEFAULT_MODE = SummarizationMode.MINIMAL

# Character budget for the text representation handed to the model. The default model's context
# window is 1,048,576 tokens, and a trace representation is dense JSON, where a token buys closer to
# 1.6 characters than the roughly 4 it buys in prose. The formatters' own 2,000,000-character
# default therefore resolves to more tokens than the window holds and the provider rejects the
# request before generating anything, so summarization sets a tighter budget of its own. A million
# characters stays under the window even at a pathological 1:1 ratio and leaves the system prompt
# and the response room to fit.
MAX_TEXT_REPR_CHARS = 1_000_000

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 120
