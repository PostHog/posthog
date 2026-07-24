class ExceptionToRetry(Exception):
    """
    Exception that makes sense to retry (not a 100% failed state), for example,
    LLMs generating an incorrect schema from the first attempt.
    """


class SummaryValidationError(Exception):
    """
    Custom exception to differ from ValueError when validating LLM responses.
    Hallucinated events or objectives should be retried immediately.
    """


class SessionSummaryModelUnavailableError(Exception):
    """
    Raised when the configured summarization model is unavailable (LLM returns a 404,
    e.g. the model was retired or renamed). Unlike transient API errors, retrying won't
    help until the model config is fixed, so this must fail fast (non-retryable) and be
    surfaced instead of being masked as a retryable error.
    """
