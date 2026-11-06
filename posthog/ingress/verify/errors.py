"""What a verifier raises when it cannot say anything about a signature."""


class VerifierUnavailable(Exception):
    """The material a verifier checks signatures against could not be obtained.

    Raised instead of answering "not verified", because a fetch that never completed proves
    nothing about the caller. The scheme turns this into `VerificationOutcome.UNAVAILABLE`,
    which the view answers with 503, so a sender that retries a server error sends the
    delivery again rather than dropping it as forged.

    This lives apart from the schemes, so a verifier module a scheme imports can raise it
    without importing the schemes back.
    """
