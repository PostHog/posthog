"""
Cloudflare Turnstile integration for challenge verification.

When WorkOS Radar answers "challenge" for a signup or a login, Turnstile is the
challenge the person solves. This module verifies Turnstile tokens against
Cloudflare's siteverify API. It also keeps a single-use nonce in Redis that ties
each challenge to the Radar attempt that asked for it, so a solved challenge can
be reported against that attempt.
"""

import uuid
import hashlib

from django.conf import settings

import requests
import structlog

from posthog.redis import get_client

logger = structlog.get_logger(__name__)

TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_VERIFY_TIMEOUT = 5.0
CHALLENGE_NONCE_TTL_SECONDS = 300


def _nonce_identity_hash(email: str, ip_address: str) -> str:
    return hashlib.sha256(f"{email.lower()}{ip_address}".encode()).hexdigest()[:16]


def verify_turnstile_token(token: str, remote_ip: str) -> bool:
    secret_key = settings.CLOUDFLARE_TURNSTILE_SECRET_KEY
    if not secret_key:
        logger.warning("turnstile_verify_no_secret_key")
        return False

    try:
        response = requests.post(
            TURNSTILE_SITEVERIFY_URL,
            data={
                "secret": secret_key,
                "response": token,
                "remoteip": remote_ip,
            },
            timeout=TURNSTILE_VERIFY_TIMEOUT,
        )
        data = response.json()
        success = data.get("success", False)
        if not success:
            logger.warning(
                "turnstile_verify_failed",
                error_codes=data.get("error-codes", []),
            )
        return bool(success)
    except requests.exceptions.Timeout:
        logger.warning("turnstile_verify_timeout")
        return False
    except Exception as e:
        logger.exception("turnstile_verify_exception", error=str(e))
        return False


# The value for a challenged attempt without a Radar ID, and the value that nonces from older releases hold
_NO_ATTEMPT_ID = "1"


def create_challenge_nonce(email: str, ip_address: str, radar_attempt_id: str = "") -> str:
    identity_hash = _nonce_identity_hash(email, ip_address)
    nonce = f"challenge:{identity_hash}:{uuid.uuid4()}"
    redis_key = f"turnstile_nonce:{nonce}"
    # The ID stays on the server, so the browser cannot name another attempt to report as a success
    get_client().setex(redis_key, CHALLENGE_NONCE_TTL_SECONDS, radar_attempt_id or _NO_ATTEMPT_ID)
    return nonce


def consume_challenge_nonce(nonce: str, email: str, ip_address: str) -> str | None:
    """Return the Radar attempt ID stored with the nonce ("" when there is none), or None when the nonce is not valid."""
    if not nonce.startswith("challenge:"):
        return None

    parts = nonce.split(":")
    if len(parts) != 3:
        return None

    expected_hash = _nonce_identity_hash(email, ip_address)
    if parts[1] != expected_hash:
        logger.warning(
            "turnstile_nonce_identity_mismatch",
            expected_hash=expected_hash,
            got_hash=parts[1],
        )
        return None

    redis_key = f"turnstile_nonce:{nonce}"
    pipeline = get_client().pipeline(transaction=True)
    pipeline.get(redis_key)
    pipeline.delete(redis_key)
    stored, deleted = pipeline.execute()
    if deleted == 0:
        logger.warning("turnstile_nonce_not_found_or_expired")
        return None

    attempt_id = stored.decode() if isinstance(stored, bytes) else str(stored)
    return "" if attempt_id == _NO_ATTEMPT_ID else attempt_id
