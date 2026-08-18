class IntegrationSecretError(Exception):
    def __init__(self, key: str, message: str) -> None:
        self.key = key
        super().__init__(message)


class SecretMissingError(IntegrationSecretError):
    """The key is unknown to the service, or has no value in this environment."""

    def __init__(self, key: str) -> None:
        super().__init__(key, f"{key} is not available from the integration service")


class SecretInRecoveryError(IntegrationSecretError):
    """The credential is known-burned and has no valid replacement yet.

    Raised instead of returning a value that cannot work, so the caller surfaces
    "reconnect needed" rather than hammering a third party with a dead credential.
    """

    def __init__(self, key: str) -> None:
        super().__init__(key, f"{key} is in recovery — the credential needs to be re-provisioned")
