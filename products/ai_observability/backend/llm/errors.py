import logging

from products.ai_observability.backend.llm.types import StreamChunk


class LLMError(Exception):
    """Base exception for LLM client errors"""


class UnsupportedModelError(LLMError):
    """Raised when an unsupported model is requested"""

    def __init__(self, model: str):
        self.model = model
        super().__init__(f"Unsupported model: {model}")


class UnsupportedProviderError(LLMError):
    """Raised when an unsupported provider is requested"""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"Unsupported provider: {provider}")


class AuthenticationError(LLMError):
    """Raised when API key authentication fails"""


class RateLimitError(LLMError):
    """Raised when rate limit is exceeded"""


class QuotaExceededError(LLMError):
    """Raised when API quota is exceeded"""


class ProviderConnectionError(LLMError):
    """Raised on a transient network/transport error talking to the provider — connection reset,
    read timeout, DNS failure. Retryable: callers should retry rather than treat it as a hard error,
    and should not log it as an exception since it's usually resolved on the next attempt."""


class ProviderMismatchError(LLMError):
    """Raised when request provider doesn't match provider key's provider"""

    def __init__(self, key_provider: str, request_provider: str):
        self.key_provider = key_provider
        self.request_provider = request_provider
        super().__init__(f"Provider key is for '{key_provider}' but request specifies '{request_provider}'")


class ModelNotFoundError(LLMError):
    """Raised when a requested model is not found"""

    def __init__(self, model: str):
        self.model = model
        super().__init__(f"Model '{model}' not found")


class StructuredOutputParseError(LLMError):
    """Raised when the LLM response cannot be parsed into the expected structured output format"""


class ContextWindowExceededError(LLMError):
    """Raised when the prompt exceeds the model's context window."""


_CONTEXT_WINDOW_ERROR_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "input tokens exceed",
    "reduce the length of the messages",
    "prompt is too long",
    "context window",
    "exceed context limit",
)


def is_context_window_error_message(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _CONTEXT_WINDOW_ERROR_MARKERS)


class ModelPermissionError(LLMError):
    """Raised when the API key doesn't have permission to access a model"""

    def __init__(self, model: str | None = None):
        self.model = model
        msg = (
            f"API key doesn't have access to model '{model}'" if model else "API key doesn't have access to this model"
        )
        super().__init__(msg)


def provider_error_detail(error: Exception | None) -> str | None:
    """The provider's own sentence, without the SDK's `Error code: NNN - {...}` wrapper.

    `str(e)` on an OpenAI or Anthropic error embeds the whole response dict, so read the parsed
    body instead. google-genai carries the same text on `message`.
    """
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        detail = body.get("error")
        if isinstance(detail, dict):
            detail = detail.get("message")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    message = getattr(error, "message", None)
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def user_facing_error_message(error: Exception | None) -> str:
    """Turn a provider failure into copy someone can act on.

    Streaming has no exception channel, so whatever text goes onto the wire is the whole
    explanation the user gets. Raw SDK output leaks provider internals without naming a next
    step, so every branch here says what to do instead.

    A failure with no branch keeps the provider's own reason. Most of those are 400s the request
    itself caused — an unsupported parameter, a malformed tool schema — where "try again" is
    advice that cannot work and the provider's sentence is the only actionable thing we have.
    """
    if isinstance(error, ModelNotFoundError):
        return f"Model '{error.model}' is not available. Pick a different model and try again."
    if isinstance(error, UnsupportedModelError):
        return f"Model '{error.model}' is not supported. Pick a different model and try again."
    if isinstance(error, ModelPermissionError):
        if error.model:
            return f"Your API key does not have access to '{error.model}'. Pick a different model, or use a key with access to it."
        return (
            "Your API key does not have access to this model. Pick a different model, or use a key with access to it."
        )
    if isinstance(error, AuthenticationError):
        return "Your provider API key was rejected. Check the key in AI observability settings."
    if isinstance(error, QuotaExceededError):
        return "Your provider API key is out of quota. Check your billing with the provider, then try again."
    if isinstance(error, RateLimitError):
        return "The provider is rate limiting this key. Wait a moment, then try again."
    if isinstance(error, ContextWindowExceededError):
        return "This conversation is too long for the model's context window. Shorten it, then try again."
    if isinstance(error, ProviderConnectionError):
        return "Could not reach the model provider. Try again."
    if isinstance(error, StructuredOutputParseError):
        return "The model returned a response we could not read. Try again."
    if isinstance(error, UnsupportedProviderError):
        return f"Provider '{error.provider}' is not supported. Pick a model from another provider."
    if isinstance(error, ProviderMismatchError):
        return (
            f"This key is for {error.key_provider}, but the request asks for {error.request_provider}. "
            "Pick a model from the key's provider, or switch keys."
        )
    detail = provider_error_detail(error)
    if detail:
        return f"The model provider rejected this request: {detail}"
    return "The request to the model provider failed. Try again."


def stream_error_chunk(
    error: Exception,
    mapped: LLMError | None,
    *,
    logger: logging.Logger,
    provider: str,
) -> StreamChunk:
    """Log a streaming failure and render the one chunk that has to explain it to the user.

    A connection error usually resolves on the next attempt, so it stays a warning rather than
    spamming error tracking.
    """
    if isinstance(mapped, ProviderConnectionError):
        logger.warning(f"{provider} connection error when streaming response: {error}")
    else:
        logger.exception(f"{provider} API error when streaming response: {error}")
    return StreamChunk(
        type="error",
        data={"error": user_facing_error_message(mapped if mapped is not None else error)},
    )
