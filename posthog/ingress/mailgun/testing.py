"""Signing a Mailgun route delivery the way Mailgun does, for tests that post to a Mailgun endpoint."""

import hmac
import time
from uuid import uuid4


def signed_mailgun_fields(signing_key: str, *, token: str | None = None, age_seconds: int = 0) -> dict[str, str]:
    """A signature triple over a timestamp `age_seconds` in the past.

    Mailgun mints a new token per delivery, and ingress dedups on it, so the default token is new on
    every call. Pass a fixed token only for a test about a redelivery or a tampered token.
    """
    timestamp = str(int(time.time()) - age_seconds)
    token = token if token is not None else uuid4().hex
    signature = hmac.digest(signing_key.encode(), f"{timestamp}{token}".encode(), "sha256").hex()
    return {"timestamp": timestamp, "token": token, "signature": signature}
