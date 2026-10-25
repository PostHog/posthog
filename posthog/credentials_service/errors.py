class CredentialsServiceFailure(Exception):
    """Base for everything the credentials service client raises.

    One base type so a caller states the policy once, instead of listing subclasses it will
    forget to update when a new one appears. Every failure below shares two properties, and
    those properties are the reason the base exists:

    1. **It is never the fault of whoever asked for the credential.** These are the OAuth app
       secrets and API keys PostHog itself owns. A product reading one cannot cause any of
       these states, cannot detect them in advance, and cannot fix them. So a caller must not
       turn one into a user-facing "your configuration is broken", and must not disable work
       the user set up. A rotation or an incident is ours to carry, not theirs.
    2. **It is never permanent.** Recovery ends when the credential is re-provisioned, a
       missing key ends when someone adds it, and an unreachable service comes back. Retrying
       is always the right shape, even when the wait is long.

    `reportable` splits them on the one axis that does differ: whether a human has to be told.
    It defaults to True so a new subclass is loud until someone decides otherwise.
    """

    reportable: bool = True


class CredentialsSecretError(CredentialsServiceFailure):
    """A failure about one specific credential, which names it."""

    def __init__(self, key: str, message: str) -> None:
        self.key = key
        super().__init__(message)


class SecretMissingError(CredentialsSecretError):
    """The key is unknown to the service, or has no value in this environment.

    Reportable: nothing resolves this on its own. Either a key never made it into the service
    for this environment, or a caller is asking for a name that does not exist. Both need a
    person, and until one looks, every read of that credential fails.
    """

    def __init__(self, key: str, disabled_reason: str | None = None) -> None:
        if disabled_reason is None:
            super().__init__(key, f"{key} is not available from the credentials service")
            return
        # The service was never called, so saying "not available from the credentials service"
        # would send the reader to look for a key that is sitting right there. Name the fallback.
        super().__init__(
            key,
            f"{key} is not set in this environment, and the credentials service was not called "
            f"({disabled_reason}) — so a key that exists only in the service cannot resolve here",
        )


class SecretInRecoveryError(CredentialsSecretError):
    """The credential is known-burned and has no valid replacement yet.

    Raised instead of returning a value that cannot work, so the caller surfaces
    "reconnect needed" rather than hammering a third party with a dead credential.

    Not reportable: somebody put this key into recovery on purpose, so an alert would tell them
    a thing they just did. Every caller of that credential fails at once, so reporting it would
    also arrive as a flood proportional to traffic rather than to the size of the problem.
    """

    reportable = False

    def __init__(self, key: str) -> None:
        super().__init__(key, f"{key} is in recovery — the credential needs to be re-provisioned")


class CredentialsServiceUnreachableError(CredentialsServiceFailure):
    """The service could not be reached, refused the request, or did not answer with usable JSON.

    Exists so no `requests` exception escapes this client. A caller that catches a bare
    `HTTPError` cannot tell our own service refusing a request from the third-party API the
    caller was actually trying to reach — and at least one caller reads a bare 404 as "the
    user's endpoint is gone" and stops their work over it. A misrouted `CREDENTIALS_SERVICE_URL`
    returns 404 too, so without this type our own deploy error would be reported as their
    mistake.

    Not reportable: the service has its own availability alerting, which sees the outage once.
    Capturing here instead would report it once per credential read, which is a measure of how
    busy PostHog is rather than of what is wrong.
    """

    reportable = False
