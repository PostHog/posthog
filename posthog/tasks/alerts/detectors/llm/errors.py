class LLMDetectorError(Exception):
    """The LLM detector could not reach a verdict for this check.

    Never swallowed into ``is_anomaly=False``: an alert that silently stops firing
    because a model call failed is worse than one that reports an error, so this
    propagates and the check is recorded as errored (after Temporal retries).
    """


class LLMDetectorUnavailableError(LLMDetectorError):
    """A transport failure, timeout, or unusable model output — worth retrying."""


class LLMDetectorMisconfiguredError(LLMDetectorError):
    """The detector cannot run as configured, so retrying cannot help.

    Today the only case is an alert with no user to attribute the model call to,
    which happens when the alert's creator is deleted.
    """
