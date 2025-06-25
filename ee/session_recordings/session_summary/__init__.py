class ExceptionToRetry(Exception):
    """
    Exception that makes sense to retry (not a 100% failed state), for example,
    LLMs generating an incorrect schema from the first attempt.
    """


class SummaryValidationError(Exception):
    """
    Custom exception to differ from ValueError when validating streaming LLM responses.
    For example, incorrect schema is expected for some state of the stream chunks, so could be ignored till the chunk is complete.
    However, hallucinated events or objectives should be retried immediately.
    """
