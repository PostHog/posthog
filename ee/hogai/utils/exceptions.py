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
