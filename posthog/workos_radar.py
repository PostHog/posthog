"""
WorkOS Radar integration for bot/fraud detection during authentication flows.

This module provides a client for the WorkOS Radar Attempts API to evaluate
signup and signin attempts for potential fraud or bot activity.

The integration operates in LOG-ONLY mode - it records the Radar decision as
a PostHog event but does not actually block or challenge users based on the verdict.
This allows evaluation of the potential impact before enabling enforcement.
"""

import time
import hashlib
from enum import StrEnum
from typing import Optional

from django.conf import settings
from django.http import HttpRequest

import requests
import structlog
import posthoganalytics

from posthog.utils import get_ip_address, get_short_user_agent

logger = structlog.get_logger(__name__)

WORKOS_RADAR_API_URL = "https://api.workos.com/radar/attempts"
WORKOS_RADAR_TIMEOUT = 5.0


class RadarAction(StrEnum):
    SIGNUP = "signup"
    SIGNIN = "login"


class RadarAuthMethod(StrEnum):
    PASSWORD = "Password"
    PASSKEY = "Passkey"


class RadarVerdict(StrEnum):
    ALLOW = "allow"
    CHALLENGE = "challenge"
    BLOCK = "block"
    ERROR = "error"
    DISABLED = "disabled"


def _hash_email(email: str) -> str:
    """Hash email for logging purposes to avoid PII in logs."""
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


def _get_raw_user_agent(request: HttpRequest) -> str:
    """Extract raw user agent from request for the WorkOS API."""
    return request.headers.get("user-agent", "")


def evaluate_auth_attempt(
    request: HttpRequest,
    email: str,
    action: RadarAction,
    auth_method: RadarAuthMethod,
    user_id: Optional[str] = None,
) -> Optional[RadarVerdict]:
    """
    Evaluate an authentication attempt using the WorkOS Radar Attempts API.

    This function operates in LOG-ONLY mode - it logs the Radar decision as a
    PostHog event but always returns the verdict without blocking.

    Args:
        request: The Django/DRF request object
        email: The email address being used for auth
        action: Whether this is a signup or signin attempt
        auth_method: The authentication method (password or passkey)
        user_id: Optional user ID if the user already exists (for signin)

    Returns:
        The Radar verdict (allow, challenge, block, error, or disabled)
    """
    if not settings.WORKOS_RADAR_ENABLED or not settings.WORKOS_RADAR_API_KEY:
        return None

    ip_address = get_ip_address(request)
    raw_user_agent = _get_raw_user_agent(request)
    short_user_agent = get_short_user_agent(request)

    start_time = time.perf_counter()
    verdict = _call_radar_api(
        email=email,
        ip_address=ip_address,
        user_agent=raw_user_agent,
        action=action,
        auth_method=auth_method,
    )
    duration_ms = (time.perf_counter() - start_time) * 1000

    _log_radar_event(
        email=email,
        user_id=user_id,
        action=action,
        auth_method=auth_method,
        verdict=verdict,
        ip_address=ip_address,
        user_agent=short_user_agent,
        duration_ms=duration_ms,
    )

    return verdict


def _call_radar_api(
    email: str,
    ip_address: str,
    user_agent: str,
    action: RadarAction,
    auth_method: RadarAuthMethod,
) -> RadarVerdict:
    """
    Make the actual API call to WorkOS Radar.
    """
    try:
        response = requests.post(
            WORKOS_RADAR_API_URL,
            headers={
                "Authorization": f"Bearer {settings.WORKOS_RADAR_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "action": action.value,
                "auth_method": auth_method.value,
            },
            timeout=WORKOS_RADAR_TIMEOUT,
        )

        if response.status_code == 200:
            data = response.json()
            verdict_str = data.get("verdict", "allow").lower()

            if verdict_str == "allow":
                return RadarVerdict.ALLOW
            elif verdict_str == "challenge":
                return RadarVerdict.CHALLENGE
            elif verdict_str == "block":
                return RadarVerdict.BLOCK
            else:
                logger.warning(
                    "workos_radar_unknown_verdict",
                    verdict=verdict_str,
                    email_hash=_hash_email(email),
                )
                return RadarVerdict.ALLOW
        else:
            logger.error(
                "workos_radar_api_error",
                status_code=response.status_code,
                response_body=response.text[:500],
                email_hash=_hash_email(email),
            )
            return RadarVerdict.ERROR

    except requests.exceptions.Timeout:
        logger.warning(
            "workos_radar_timeout",
            email_hash=_hash_email(email),
        )
        return RadarVerdict.ERROR
    except Exception as e:
        logger.exception(
            "workos_radar_exception",
            email_hash=_hash_email(email),
            error=str(e),
        )
        return RadarVerdict.ERROR


def _log_radar_event(
    email: str,
    user_id: Optional[str],
    action: RadarAction,
    auth_method: RadarAuthMethod,
    verdict: RadarVerdict,
    ip_address: str,
    user_agent: str,
    duration_ms: float,
) -> None:
    """
    Log the Radar decision as a PostHog event for analysis.
    """
    distinct_id = user_id or f"pre_signup_{_hash_email(email)}"

    properties = {
        "action": action.value,
        "auth_method": auth_method.value,
        "verdict": verdict.value,
        "would_challenge": verdict == RadarVerdict.CHALLENGE,
        "would_block": verdict == RadarVerdict.BLOCK,
        "is_error": verdict == RadarVerdict.ERROR,
        "ip_address_hash": hashlib.sha256(ip_address.encode()).hexdigest()[:16],
        "user_agent": user_agent,
        "email_domain": email.split("@")[-1] if "@" in email else "",
        "radar_api_duration_ms": round(duration_ms, 2),
    }

    posthoganalytics.capture(
        distinct_id=distinct_id,
        event="workos_radar_attempt",
        properties=properties,
    )

    logger.info(
        "workos_radar_attempt_logged",
        action=action.value,
        auth_method=auth_method.value,
        verdict=verdict.value,
        email_hash=_hash_email(email),
        duration_ms=round(duration_ms, 2),
    )
