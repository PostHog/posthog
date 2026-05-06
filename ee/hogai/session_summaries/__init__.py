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
