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

    The creator is missing, AI data processing consent is withdrawn, or the rollout is disabled.
    """
