import openai
import anthropic
from prometheus_client import Counter

LLM_API_EXCEPTIONS = (anthropic.APIError, openai.APIError)

LLM_PROVIDER_ERROR_COUNTER = Counter(
    "posthog_ai_llm_provider_errors_total",
    "Total number of LLM provider API errors",
    ["provider"],
)


class GenerationCanceled(Exception):
    """Raised when generation is canceled."""

    pass


class LLMProviderError(Exception):
    """
    Wraps errors from LLM providers to provide consistent error handling better user-facing messages.
    """

    def __init__(self, message: str, original_error: Exception | None = None, provider: str | None = None):
        self.message = message
        self.original_error = original_error
        self.provider = provider
        super().__init__(message)
