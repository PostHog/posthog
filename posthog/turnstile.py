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
OPEN_CHALLENGE_LIMIT = 20
OPEN_CHALLENGE_WINDOW_SECONDS = 600


def _nonce_identity_hash(email: str, ip_address: str) -> str:
    return hashlib.sha256(f"{email.lower()}{ip_address}".encode()).hexdigest()[:16]


def _open_challenges_key(identity_hash: str) -> str:
    return f"turnstile_open:{identity_hash}"


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


class TooManyOpenChallenges(Exception):
    """The address left OPEN_CHALLENGE_LIMIT challenges unsolved from this IP."""


def create_challenge_nonce(email: str, ip_address: str, *, action: str, radar_attempt_id: str = "") -> str:
    """Store a nonce for a new challenge, or raise TooManyOpenChallenges. The count is per address and IP, so
    other people behind the IP are not blocked."""
    identity_hash = _nonce_identity_hash(email, ip_address)
    nonce = f"challenge:{identity_hash}:{uuid.uuid4()}"
    redis_key = f"turnstile_nonce:{nonce}"
    open_key = _open_challenges_key(identity_hash)
    now = time.time()
    client = get_client()
    pipeline = client.pipeline(transaction=True)
    pipeline.zremrangebyscore(open_key, 0, now - OPEN_CHALLENGE_WINDOW_SECONDS)
    # The add and the count run in one transaction, so concurrent requests cannot all pass the limit
    pipeline.zadd(open_key, {nonce: now})
    pipeline.zcard(open_key)
    pipeline.expire(open_key, OPEN_CHALLENGE_WINDOW_SECONDS)
    # The action and the ID stay on the server, so the browser can change neither of them
    pipeline.setex(redis_key, CHALLENGE_NONCE_TTL_SECONDS, f"{action}:{radar_attempt_id or _NO_ATTEMPT_ID}")
    _, _, open_challenges, _, _ = pipeline.execute()
    if open_challenges <= OPEN_CHALLENGE_LIMIT:
        return nonce
    pipeline = client.pipeline(transaction=True)
    pipeline.zrem(open_key, nonce)
    pipeline.delete(redis_key)
    pipeline.execute()
    raise TooManyOpenChallenges()


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
    pipeline.zrem(_open_challenges_key(expected_hash), nonce)
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
