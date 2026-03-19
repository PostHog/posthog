"""Mailgun integration helpers for conversations email channel."""

import hmac
import time
import hashlib

from posthog.models.instance_setting import get_instance_setting

WEBHOOK_TIMESTAMP_MAX_AGE_SECONDS = 300  # 5 minutes


def validate_webhook_signature(token: str, timestamp: str, signature: str) -> bool:
    """Verify inbound Mailgun webhook authenticity via HMAC-SHA256.

    Also rejects timestamps older than 5 minutes to prevent replay attacks.
    """
    # Uncomment this to allow debugging in development
    # if settings.DEBUG:
    #    return True

    signing_key = get_instance_setting("CONVERSATIONS_EMAIL_WEBHOOK_SIGNING_KEY")
    if not signing_key:
        return False

    # Reject stale timestamps
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > WEBHOOK_TIMESTAMP_MAX_AGE_SECONDS:
        return False

    expected = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
