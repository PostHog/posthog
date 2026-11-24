"""
Cloudflare Turnstile integration for challenge verification.

When WorkOS Radar answers "challenge" for a signup or a login, Turnstile is the
challenge the person solves. This module verifies Turnstile tokens against
Cloudflare's siteverify API. It also keeps a single-use nonce in Redis that ties
each challenge to the Radar attempt that asked for it, so a solved challenge can
be reported against that attempt.
"""

import time
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
# An IP with this many challenges left unsolved in the window gets a block in place of another challenge
OPEN_CHALLENGE_LIMIT = 20
OPEN_CHALLENGE_WINDOW_SECONDS = 600


def _nonce_identity_hash(email: str, ip_address: str) -> str:
    return hashlib.sha256(f"{email.lower()}{ip_address}".encode()).hexdigest()[:16]


def _open_challenges_key(ip_address: str) -> str:
    return f"turnstile_open:{hashlib.sha256(ip_address.encode()).hexdigest()[:16]}"


def has_too_many_open_challenges(ip_address: str) -> bool:
    """Whether the IP left too many challenges unsolved. A solved challenge does not count, so real users behind one IP do not add up."""
    key = _open_challenges_key(ip_address)
    try:
        pipeline = get_client().pipeline(transaction=True)
        pipeline.zremrangebyscore(key, 0, time.time() - OPEN_CHALLENGE_WINDOW_SECONDS)
        pipeline.zcard(key)
        _, open_challenges = pipeline.execute()
    except Exception:
        logger.warning("turnstile_open_challenge_count_failed", exc_info=True)
        return False
    return open_challenges >= OPEN_CHALLENGE_LIMIT


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
# Nonces from older releases hold no action, and only signup issued them
_LEGACY_ACTION = "signup"


def create_challenge_nonce(email: str, ip_address: str, *, action: str, radar_attempt_id: str = "") -> str:
    identity_hash = _nonce_identity_hash(email, ip_address)
    nonce = f"challenge:{identity_hash}:{uuid.uuid4()}"
    redis_key = f"turnstile_nonce:{nonce}"
    # The action and the ID stay on the server, so a solved login challenge cannot complete a signup
    # and the browser cannot name another attempt to report as a success
    pipeline = get_client().pipeline(transaction=True)
    pipeline.setex(redis_key, CHALLENGE_NONCE_TTL_SECONDS, f"{action}:{radar_attempt_id or _NO_ATTEMPT_ID}")
    pipeline.zadd(_open_challenges_key(ip_address), {nonce: time.time()})
    pipeline.expire(_open_challenges_key(ip_address), OPEN_CHALLENGE_WINDOW_SECONDS)
    pipeline.execute()
    return nonce


def consume_challenge_nonce(nonce: str, email: str, ip_address: str, *, action: str) -> str | None:
    """Return the Radar attempt ID stored with the nonce ("" when there is none), or None when the nonce is not
    valid for this address, IP and action."""
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
    # A failed answer is not unsolved either: it refuses the attempt, and the lockout counts that
    pipeline.zrem(_open_challenges_key(ip_address), nonce)
    stored, deleted, _ = pipeline.execute()
    if deleted == 0:
        logger.warning("turnstile_nonce_not_found_or_expired")
        return None

    value = stored.decode() if isinstance(stored, bytes) else str(stored)
    stored_action, _, attempt_id = value.rpartition(":")
    if (stored_action or _LEGACY_ACTION) != action:
        logger.warning("turnstile_nonce_action_mismatch", expected=action, got=stored_action or _LEGACY_ACTION)
        return None
    return "" if attempt_id == _NO_ATTEMPT_ID else attempt_id
