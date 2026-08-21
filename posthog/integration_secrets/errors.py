class IntegrationSecretError(Exception):
    def __init__(self, key: str, message: str) -> None:
        self.key = key
        super().__init__(message)


class SecretMissingError(IntegrationSecretError):
    """The key is unknown to the service, or has no value in this environment."""

    def __init__(self, key: str, disabled_reason: str | None = None) -> None:
        if disabled_reason is None:
            super().__init__(key, f"{key} is not available from the integration service")
            return
        # The service was never called, so saying "not available from the integration service"
        # would send the reader to look for a key that is sitting right there. Name the fallback.
        super().__init__(
            key,
            f"{key} is not set in this environment, and the integration service was not called "
            f"({disabled_reason}) — so a key that exists only in the service cannot resolve here",
        )


class IntegrationServiceMisconfiguredError(Exception):
    """Half-configured: one of the two variables is set and the other is not.

    Both unset is a valid state — self-hosted and local development don't run the service, and
    reading the environment is the whole point of the fallback. One without the other is a state
    nobody chose, and it is invisible: it reads as "not configured", so credentials still mounted
    as environment variables resolve as if the service answered, while the ones that have actually
    moved raise SecretMissingError. Refuse instead, and name the variable to set.
    """

    def __init__(self, missing: str) -> None:
        self.missing = missing
        super().__init__(
            f"{missing} is not set. The integration service client needs both "
            f"INTEGRATION_SERVICE_URL and INTEGRATION_SERVICE_JWT_SECRET, or neither "
            f"(which reads credentials from the environment, as self-hosted does)."
        )


class SecretInRecoveryError(IntegrationSecretError):
    """The credential is known-burned and has no valid replacement yet.

    Raised instead of returning a value that cannot work, so the caller surfaces
    "reconnect needed" rather than hammering a third party with a dead credential.
    """

    def __init__(self, key: str) -> None:
        super().__init__(key, f"{key} is in recovery — the credential needs to be re-provisioned")
