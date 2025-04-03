class ExceptionToRetry(Exception):
    """
    Exception that makes sense to retry (not a 100% failed state), for example,
    LLMs generating an incorrect schema from the first attempt.
    """
