"""
WorkOS Radar integration for bot/fraud detection during authentication flows.

This module provides a client for the WorkOS Radar Attempts API to evaluate
signup and password login attempts for potential fraud or bot activity. When
Radar returns a BLOCK verdict, the attempt is rejected with a
SuspiciousAttemptBlocked exception unless a security access rule exempts that
address from the signup risk check.

Signup always acts on the verdict. Password login follows the
WORKOS_RADAR_LOGIN_MODE instance setting, so the verdicts can be recorded
before any login is refused.
"""

import re
import time
import hashlib
from enum import StrEnum
from typing import Optional

from django.conf import settings
from django.http import HttpRequest

import requests
import structlog
import posthoganalytics
from rest_framework.exceptions import APIException

from posthog.models.instance_setting import get_instance_setting
from posthog.turnstile import create_challenge_nonce, validate_and_consume_nonce, verify_turnstile_token
from posthog.utils import get_ip_address, get_short_user_agent

from products.security.backend.facade.api import is_signup_risk_exempt

logger = structlog.get_logger(__name__)

WORKOS_RADAR_API_URL = "https://api.workos.com/radar/attempts"
WORKOS_RADAR_TIMEOUT = 5.0
# Every login waits on this call, so login gets a shorter timeout than signup
WORKOS_RADAR_LOGIN_TIMEOUT = 2.0


class SuspiciousAttemptBlocked(APIException):
    status_code = 403
    default_detail = "Your account has been flagged for suspicious activity."
    default_code = "suspicious_attempt_blocked"
    default_type = "authentication_error"


class ChallengeRequired(APIException):
    status_code = 428
    default_detail = "Additional verification is required to complete signup."
    default_code = "challenge_required"
    default_type = "authentication_error"

    def __init__(self, challenge_nonce: str, turnstile_site_key: str):
        super().__init__()
        self.extra = {
            "challenge_nonce": challenge_nonce,
            "turnstile_site_key": turnstile_site_key,
        }


class RadarAction(StrEnum):
    SIGNUP = "signup"
    SIGNIN = "login"


# The Attempts API documents `sign-in`. Signup keeps the value production already sends, and
# the analytics event keeps the enum values.
_ATTEMPTS_API_ACTION = {RadarAction.SIGNUP: "signup", RadarAction.SIGNIN: "sign-in"}


class RadarAuthMethod(StrEnum):
    PASSWORD = "Password"
    PASSKEY = "Passkey"
    OTHER = "Other"


class RadarVerdict(StrEnum):
    ALLOW = "allow"
    CHALLENGE = "challenge"
    BLOCK = "block"
    ERROR = "error"
    DISABLED = "disabled"


class RadarMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


# The browser sends this token, so a value outside this shape is dropped rather than sent to WorkOS
_SIGNALS_ID_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,512}")


def _hash_email(email: str) -> str:
    """Hash email for logging purposes to avoid PII in logs."""
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


def _is_radar_configured() -> bool:
    return bool(settings.WORKOS_RADAR_ENABLED and settings.WORKOS_RADAR_API_KEY)


def get_radar_login_mode() -> RadarMode:
    value = str(get_instance_setting("WORKOS_RADAR_LOGIN_MODE") or "").strip().lower()
    try:
        return RadarMode(value)
    except ValueError:
        return RadarMode.OFF


def _sample_key(email: str, account_id: Optional[str]) -> str:
    # The account ID, when there is one, puts every spelling of its address in the same bucket
    return account_id or email.strip().lower()


def _is_sampled_for_login(sample_key: str) -> bool:
    # A fixed bucket gives Radar every login of a sampled account, so it learns the account's devices
    percent = int(get_instance_setting("WORKOS_RADAR_LOGIN_SAMPLE_PERCENT"))
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    bucket = int(hashlib.sha256(sample_key.encode()).hexdigest()[:8], 16) % 100
    return bucket < percent


def _login_mode_for(sample_key: str) -> RadarMode:
    """Radar mode for a password login. A settings error turns Radar off."""
    try:
        mode = get_radar_login_mode()
        if mode == RadarMode.OFF or not _is_sampled_for_login(sample_key):
            return RadarMode.OFF
        return mode
    except Exception:
        logger.exception("workos_radar_login_mode_read_failed")
        return RadarMode.OFF


def _radar_mode_for(action: RadarAction, auth_method: RadarAuthMethod, sample_key: str) -> RadarMode:
    if action == RadarAction.SIGNUP:
        return RadarMode.ENFORCE
    # Credential stuffing tries leaked passwords, so a passkey login gains nothing from the check
    if action == RadarAction.SIGNIN and auth_method == RadarAuthMethod.PASSWORD:
        return _login_mode_for(sample_key)
    return RadarMode.OFF


def radar_client_id_for_login(email: str, account_id: Optional[str] = None) -> str:
    """WorkOS client ID for the login page's Radar browser script, or "" when Radar skips this login."""
    if not settings.WORKOS_RADAR_CLIENT_ID or not _is_radar_configured():
        return ""
    if _login_mode_for(_sample_key(email, account_id)) == RadarMode.OFF:
        return ""
    return settings.WORKOS_RADAR_CLIENT_ID


def _clean_signals_id(value: str) -> str:
    return value if _SIGNALS_ID_PATTERN.fullmatch(value) else ""


def _get_raw_user_agent(request: HttpRequest) -> str:
    """Extract raw user agent from request for the WorkOS API."""
    return request.headers.get("user-agent", "")


def evaluate_auth_attempt(
    request: HttpRequest,
    email: str,
    action: RadarAction,
    auth_method: RadarAuthMethod,
    user_id: Optional[str] = None,
    turnstile_token: str = "",
    challenge_nonce: str = "",
    challenge_allowed: bool = True,
    call_site: Optional[str] = None,
    signals_id: str = "",
    account_id: Optional[str] = None,
) -> Optional[RadarVerdict]:
    """
    Evaluate an authentication attempt using the WorkOS Radar Attempts API.

    ``challenge_allowed=False`` is for a caller with no way to show a Turnstile
    challenge, such as a partner server or the login form. A CHALLENGE verdict then
    lets the attempt through, so that only a BLOCK verdict refuses it.

    A password login runs only when WORKOS_RADAR_LOGIN_MODE is not "off" and the
    address is in the sample. In "shadow" mode the verdict is recorded and never
    refuses the login.

    ``signals_id`` is the token from the WorkOS Radar browser script. It links the
    device signals that the browser collected to this attempt. ``account_id`` is the
    ID of the account the address resolves to, and it decides the login sample.

    Raises:
        SuspiciousAttemptBlocked: When verdict is BLOCK, the mode enforces it, and
            no access rule exempts the address from the signup risk check.
        ChallengeRequired: When verdict is CHALLENGE, the mode enforces it,
            ``challenge_allowed`` is True, and no valid Turnstile token was provided.
    """
    if not _is_radar_configured():
        return None

    mode = _radar_mode_for(action, auth_method, _sample_key(email, account_id))
    if mode == RadarMode.OFF:
        return None

    ip_address = get_ip_address(request)
    short_user_agent = get_short_user_agent(request)
    signals_id = _clean_signals_id(signals_id)

    verdict, duration_ms = _evaluate_verdict(
        email=email,
        ip_address=ip_address,
        user_agent=_get_raw_user_agent(request),
        action=action,
        auth_method=auth_method,
        turnstile_token=turnstile_token,
        challenge_nonce=challenge_nonce,
        signals_id=signals_id,
        timeout=WORKOS_RADAR_LOGIN_TIMEOUT if action == RadarAction.SIGNIN else WORKOS_RADAR_TIMEOUT,
    )

    outcome = _decide_outcome(verdict, email, turnstile_token, challenge_nonce, ip_address)
    if outcome == "challenge" and not challenge_allowed:
        outcome = "allow"
    if mode == RadarMode.SHADOW and outcome in ("block", "challenge"):
        outcome = "allow"

    _log_radar_event(
        email=email,
        user_id=user_id,
        action=action,
        auth_method=auth_method,
        verdict=verdict,
        ip_address=ip_address,
        user_agent=short_user_agent,
        duration_ms=duration_ms,
        was_blocked=outcome == "block",
        was_bypassed=outcome == "bypass",
        # Only access rules bypass Radar now, but the property stays so queries written
        # while the Redis list existed keep working and the event still says why.
        bypass_source="rule" if outcome == "bypass" else None,
        was_challenged=outcome == "challenge",
        was_challenge_completed=outcome == "completed",
        call_site=call_site,
        mode=mode,
        signals_sent=bool(signals_id),
    )

    if outcome == "block":
        logger.warning("workos_radar_attempt_blocked", action=action.value, email_hash=_hash_email(email))
        raise SuspiciousAttemptBlocked()

    if outcome == "challenge":
        if not settings.CLOUDFLARE_TURNSTILE_SITE_KEY:
            logger.error("workos_radar_challenge_no_site_key", action=action.value, email_hash=_hash_email(email))
            raise SuspiciousAttemptBlocked()

        nonce = create_challenge_nonce(email, ip_address)
        logger.info("workos_radar_challenge_issued", action=action.value, email_hash=_hash_email(email))
        raise ChallengeRequired(
            challenge_nonce=nonce,
            turnstile_site_key=settings.CLOUDFLARE_TURNSTILE_SITE_KEY,
        )

    return verdict


def _evaluate_verdict(
    email: str,
    ip_address: str,
    user_agent: str,
    action: RadarAction,
    auth_method: RadarAuthMethod,
    turnstile_token: str,
    challenge_nonce: str,
    signals_id: str = "",
    timeout: float = WORKOS_RADAR_TIMEOUT,
) -> tuple[RadarVerdict, float]:
    """Return (verdict, api_duration_ms). Skip the Radar API call on challenge resubmits."""
    if turnstile_token and challenge_nonce:
        return RadarVerdict.CHALLENGE, 0.0

    start_time = time.perf_counter()
    verdict = _call_radar_api(
        email=email,
        ip_address=ip_address,
        user_agent=user_agent,
        action=action,
        auth_method=auth_method,
        signals_id=signals_id,
        timeout=timeout,
    )
    return verdict, (time.perf_counter() - start_time) * 1000


def _decide_outcome(
    verdict: RadarVerdict,
    email: str,
    turnstile_token: str,
    challenge_nonce: str,
    ip_address: str,
) -> str:
    """Return one of: 'allow', 'block', 'bypass', 'challenge', 'completed'."""
    if turnstile_token and challenge_nonce:
        nonce_valid = validate_and_consume_nonce(challenge_nonce, email, ip_address)
        token_valid = nonce_valid and verify_turnstile_token(turnstile_token, ip_address)
        return "completed" if token_valid else "block"

    if verdict in (RadarVerdict.BLOCK, RadarVerdict.CHALLENGE) and is_signup_risk_exempt(email):
        return "bypass"

    if verdict == RadarVerdict.BLOCK:
        return "block"

    if verdict == RadarVerdict.CHALLENGE:
        return "challenge"

    return "allow"


def _post_attempt(payload: dict[str, str], timeout: float) -> requests.Response:
    return requests.post(
        WORKOS_RADAR_API_URL,
        headers={
            "Authorization": f"Bearer {settings.WORKOS_RADAR_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )


def _call_radar_api(
    email: str,
    ip_address: str,
    user_agent: str,
    action: RadarAction,
    auth_method: RadarAuthMethod,
    signals_id: str = "",
    timeout: float = WORKOS_RADAR_TIMEOUT,
) -> RadarVerdict:
    """
    Make the actual API call to WorkOS Radar.
    """
    try:
        payload: dict[str, str] = {
            "email": email,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "action": _ATTEMPTS_API_ACTION[action],
            "auth_method": auth_method.value,
        }
        if signals_id:
            payload["signals_id"] = signals_id
        response = _post_attempt(payload, timeout)

        # The browser sends the signals token, so a caller can send one that WorkOS refuses. An
        # API error lets the attempt through, so the check runs again without the token rather
        # than letting a bad token skip Radar.
        if signals_id and 400 <= response.status_code < 500 and response.status_code != 429:
            logger.warning(
                "workos_radar_signals_rejected",
                status_code=response.status_code,
                email_hash=_hash_email(email),
            )
            response = _post_attempt({key: value for key, value in payload.items() if key != "signals_id"}, timeout)

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
    was_blocked: bool = False,
    was_bypassed: bool = False,
    bypass_source: Optional[str] = None,
    was_challenged: bool = False,
    was_challenge_completed: bool = False,
    call_site: Optional[str] = None,
    mode: RadarMode = RadarMode.ENFORCE,
    signals_sent: bool = False,
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
        "was_blocked": was_blocked,
        "was_bypassed": was_bypassed,
        "bypass_source": bypass_source,
        "was_challenged": was_challenged,
        "was_challenge_completed": was_challenge_completed,
        "is_error": verdict == RadarVerdict.ERROR,
        "ip_address_hash": hashlib.sha256(ip_address.encode()).hexdigest()[:16],
        "user_agent": user_agent,
        "email_domain": email.split("@")[-1] if "@" in email else "",
        "radar_api_duration_ms": round(duration_ms, 2),
        "call_site": call_site,
        "mode": mode.value,
        "signals_sent": signals_sent,
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
        bypass_source=bypass_source,
        email_hash=_hash_email(email),
        duration_ms=round(duration_ms, 2),
        mode=mode.value,
        signals_sent=signals_sent,
    )
