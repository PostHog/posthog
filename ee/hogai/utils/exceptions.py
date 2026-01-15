import openai
import anthropic
from prometheus_client import Counter

# All LLM API exceptions (for catching)
LLM_API_EXCEPTIONS = (anthropic.APIError, openai.APIError)

# Transient errors that may resolve on retry (5xx, rate limits, timeouts, connection issues)
LLM_TRANSIENT_EXCEPTIONS = (
    # Anthropic transient errors
    anthropic.InternalServerError,
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    # OpenAI transient errors
    openai.InternalServerError,
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
)

# Client/validation errors that won't resolve on retry (400, 422, etc.)
LLM_CLIENT_EXCEPTIONS = (
    # Anthropic client errors
    anthropic.BadRequestError,
    anthropic.UnprocessableEntityError,
    # OpenAI client errors
    openai.BadRequestError,
    openai.UnprocessableEntityError,
)

LLM_PROVIDER_ERROR_COUNTER = Counter(
    "posthog_ai_llm_provider_errors_total",
    "Total number of LLM provider API errors (transient)",
    ["provider"],
)

LLM_CLIENT_ERROR_COUNTER = Counter(
    "posthog_ai_llm_client_errors_total",
    "Total number of LLM client/validation errors",
    ["provider"],
)


class GenerationCanceled(Exception):
    """Raised when generation is canceled."""

    pass
