class MissingRequiredInputsError(RuntimeError):
    """We are unable to recover due to some input being missing.

    This exists to signal an impossible runtime state. At the time of writing,
    it should not be possible to get into this state, but if we ever see this,
    it's likely a signal of a bug.
    """

    pass
