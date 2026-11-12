"""
Cloudflare Turnstile integration for challenge verification.

Provides token verification against Cloudflare's siteverify API and
single-use nonce management via Redis for tying challenges to specific
signup attempts.
"""

import time
import uuid
import hashlib
from enum import StrEnum

from django.conf import settings

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.egress.cloudflare_turnstile import TURNSTILE_SITEVERIFY_URL, turnstile_siteverify_request
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

TURNSTILE_VERIFY_TIMEOUT = 5.0
CHALLENGE_NONCE_TTL_SECONDS = 300

LOGIN_SITEVERIFY_TIMEOUT_SECONDS = 2.0
LOGIN_TURNSTILE_ACTION = "login"
TURNSTILE_TOKEN_MAX_LENGTH = 2048
# Cloudflare's published test secrets return no `action`, so the action check cannot apply to them.
CLOUDFLARE_TEST_SECRET_KEYS = frozenset(
    {
        "1x0000000000000000000000000000000AA",
        "2x0000000000000000000000000000000AA",
        "3x0000000000000000000000000000000AA",
    }
)


class SiteverifyResult(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


@frozen
class SiteverifyOutcome:
    result: SiteverifyResult
    error_codes: tuple[str, ...] = ()
    duration_seconds: float = 0.0


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


def create_challenge_nonce(email: str, ip_address: str) -> str:
    identity_hash = _nonce_identity_hash(email, ip_address)
    nonce = f"challenge:{identity_hash}:{uuid.uuid4()}"
    redis_key = f"turnstile_nonce:{nonce}"
    get_client().setex(redis_key, CHALLENGE_NONCE_TTL_SECONDS, "1")
    return nonce


def validate_and_consume_nonce(nonce: str, email: str, ip_address: str) -> bool:
    if not nonce.startswith("challenge:"):
        return False

    parts = nonce.split(":")
    if len(parts) != 3:
        return False

    expected_hash = _nonce_identity_hash(email, ip_address)
    if parts[1] != expected_hash:
        logger.warning(
            "turnstile_nonce_identity_mismatch",
            expected_hash=expected_hash,
            got_hash=parts[1],
        )
        return False

    redis_key = f"turnstile_nonce:{nonce}"
    deleted = get_client().delete(redis_key)
    if deleted == 0:
        logger.warning("turnstile_nonce_not_found_or_expired")
        return False

    return True


def verify_login_turnstile_token(token: str, remote_ip: str) -> SiteverifyOutcome:
    if len(token) > TURNSTILE_TOKEN_MAX_LENGTH:
        return SiteverifyOutcome(result=SiteverifyResult.REJECTED, error_codes=("token-too-long",))

    secret_key = settings.CLOUDFLARE_TURNSTILE_SECRET_KEY
    start = time.perf_counter()
    try:
        response = turnstile_siteverify_request(
            {"secret": secret_key, "response": token, "remoteip": remote_ip},
            source="login_turnstile",
            timeout=LOGIN_SITEVERIFY_TIMEOUT_SECONDS,
        )
        data = None if response.status_code >= 500 else response.json()
    except (requests.RequestException, ValueError):
        data = None
    duration_seconds = time.perf_counter() - start

    if not isinstance(data, dict):
        return SiteverifyOutcome(result=SiteverifyResult.UNAVAILABLE, duration_seconds=duration_seconds)

    error_codes = tuple(str(code) for code in data.get("error-codes") or [])
    if not data.get("success"):
        result = SiteverifyResult.UNAVAILABLE if "internal-error" in error_codes else SiteverifyResult.REJECTED
        return SiteverifyOutcome(result=result, error_codes=error_codes, duration_seconds=duration_seconds)

    if secret_key not in CLOUDFLARE_TEST_SECRET_KEYS and data.get("action") != LOGIN_TURNSTILE_ACTION:
        return SiteverifyOutcome(
            result=SiteverifyResult.REJECTED, error_codes=("action-mismatch",), duration_seconds=duration_seconds
        )

    return SiteverifyOutcome(result=SiteverifyResult.ACCEPTED, duration_seconds=duration_seconds)
