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

Radar learns which earlier attempts succeeded only when PostHog reports them,
and some of its controls, such as impossible travel, depend on that history.
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

from posthog.dataclasses import frozen
from posthog.models.instance_setting import get_instance_setting
from posthog.turnstile import consume_challenge_nonce, create_challenge_nonce, verify_turnstile_token
from posthog.utils import _normalize_ip, get_ip_address, get_short_user_agent, get_trusted_client_ip

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


@frozen
class RadarAttempt:
    verdict: RadarVerdict
    attempt_id: str = ""
    challenge_completed: bool = False


class RadarReportFailed(Exception):
    """WorkOS could not take a success report now, so the report can go again later."""

    def __init__(self, status_code: int, retry_after: Optional[int] = None):
        super().__init__(f"WorkOS answered {status_code}")
        self.retry_after = retry_after


_MAX_RETRY_AFTER_SECONDS = 3600


# The browser sends this token, so a value outside this shape is dropped rather than sent to WorkOS
_SIGNALS_ID_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,512}")
# The ID goes into the URL path of the success report
_ATTEMPT_ID_PATTERN = re.compile(r"[A-Za-z0-9_]{1,128}")


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


def _login_mode_for(sample_key: Optional[str]) -> RadarMode:
    """Radar mode for a password login, or for any login when ``sample_key`` is None. A settings error turns Radar off."""
    try:
        mode = get_radar_login_mode()
        if mode == RadarMode.OFF or (sample_key is not None and not _is_sampled_for_login(sample_key)):
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


def radar_client_id_for_login() -> str:
    """WorkOS client ID for the login page's Radar browser script, or "" while Radar checks no logins."""
    if not settings.WORKOS_RADAR_CLIENT_ID or not _is_radar_configured():
        return ""
    # The precheck needs no authentication, so every address gets the same answer and the
    # response does not show which accounts are outside the sample
    if _login_mode_for(None) == RadarMode.OFF:
        return ""
    return settings.WORKOS_RADAR_CLIENT_ID


def _client_ip_for_radar(request: HttpRequest) -> str:
    trusted_ip = get_trusted_client_ip(request)
    if trusted_ip:
        return trusted_ip
    trusted_proxies = {proxy.strip() for proxy in (settings.TRUSTED_PROXIES or "").split(",") if proxy.strip()}
    remote_addr = request.META.get("REMOTE_ADDR") or ""
    if settings.USE_X_FORWARDED_HOST and trusted_proxies:
        # The nearest hop that no trusted proxy vouches for is the client, so a forged left-most entry is ignored
        forwarded = [hop.strip() for hop in (request.headers.get("x-forwarded-for") or "").split(",") if hop.strip()]
        for hop in reversed([*forwarded, remote_addr]):
            hop_ip = _normalize_ip(hop)
            if hop_ip is None:
                break
            if hop_ip not in trusted_proxies:
                return hop_ip
        return _normalize_ip(remote_addr) or remote_addr
    # Without trusted proxies the connecting address is often a proxy shared by every login
    return get_ip_address(request)


def _clean_signals_id(value: str) -> str:
    return value if _SIGNALS_ID_PATTERN.fullmatch(value) else ""


def _get_raw_user_agent(request: HttpRequest) -> str:
    """Extract raw user agent from request for the WorkOS API."""
    # WorkOS requires the field, and an error lets the attempt through, so a caller cannot skip
    # Radar by leaving the header out or sending one far longer than any browser does
    return request.headers.get("user-agent", "")[:1024] or "unknown"


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
) -> Optional[RadarAttempt]:
    """
    Evaluate an authentication attempt using the WorkOS Radar Attempts API.

    Returns the attempt, or None when Radar is off for it. Once the sign-up or sign-in
    succeeds, the caller reports the attempt with
    ``posthog.tasks.workos_radar.report_attempt_success``.

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

    ip_address = _client_ip_for_radar(request)
    short_user_agent = get_short_user_agent(request)
    signals_id = _clean_signals_id(signals_id)

    if turnstile_token and challenge_nonce:
        # A resubmit answers the challenge of an earlier attempt, so Radar is not called again
        challenge_attempt_id = _complete_challenge(email, turnstile_token, challenge_nonce, ip_address)
        attempt = RadarAttempt(
            verdict=RadarVerdict.CHALLENGE,
            attempt_id=challenge_attempt_id or "",
            challenge_completed=challenge_attempt_id is not None,
        )
        duration_ms = 0.0
        outcome = "completed" if attempt.challenge_completed else "block"
    else:
        attempt, duration_ms = _evaluate_verdict(
            email=email,
            ip_address=ip_address,
            user_agent=_get_raw_user_agent(request),
            action=action,
            auth_method=auth_method,
            signals_id=signals_id,
            timeout=WORKOS_RADAR_LOGIN_TIMEOUT if action == RadarAction.SIGNIN else WORKOS_RADAR_TIMEOUT,
        )
        outcome = _decide_outcome(attempt.verdict, email, action)
    if outcome == "challenge" and not challenge_allowed:
        outcome = "allow"
    if mode == RadarMode.SHADOW and outcome in ("block", "challenge"):
        outcome = "allow"

    _log_radar_event(
        email=email,
        user_id=user_id,
        action=action,
        auth_method=auth_method,
        verdict=attempt.verdict,
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

        nonce = create_challenge_nonce(email, ip_address, radar_attempt_id=attempt.attempt_id)
        logger.info("workos_radar_challenge_issued", action=action.value, email_hash=_hash_email(email))
        raise ChallengeRequired(
            challenge_nonce=nonce,
            turnstile_site_key=settings.CLOUDFLARE_TURNSTILE_SITE_KEY,
        )

    return attempt


def _evaluate_verdict(
    email: str,
    ip_address: str,
    user_agent: str,
    action: RadarAction,
    auth_method: RadarAuthMethod,
    signals_id: str = "",
    timeout: float = WORKOS_RADAR_TIMEOUT,
) -> tuple[RadarAttempt, float]:
    """Return (attempt, api_duration_ms)."""
    start_time = time.perf_counter()
    attempt = _call_radar_api(
        email=email,
        ip_address=ip_address,
        user_agent=user_agent,
        action=action,
        auth_method=auth_method,
        signals_id=signals_id,
        timeout=timeout,
    )
    return attempt, (time.perf_counter() - start_time) * 1000


def _complete_challenge(email: str, turnstile_token: str, challenge_nonce: str, ip_address: str) -> Optional[str]:
    """Return the ID of the challenged attempt ("" when Radar gave none), or None when the challenge fails."""
    attempt_id = consume_challenge_nonce(challenge_nonce, email, ip_address)
    if attempt_id is None or not verify_turnstile_token(turnstile_token, ip_address):
        return None
    return attempt_id


def _decide_outcome(verdict: RadarVerdict, email: str, action: RadarAction = RadarAction.SIGNUP) -> str:
    """Return one of: 'allow', 'block', 'bypass', 'challenge'."""
    # The exemption rules cover account creation only, so a login never inherits them
    if (
        action == RadarAction.SIGNUP
        and verdict in (RadarVerdict.BLOCK, RadarVerdict.CHALLENGE)
        and is_signup_risk_exempt(email)
    ):
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
) -> RadarAttempt:
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
            attempt_id = str(data.get("attempt_id") or "")

            if verdict_str == "allow":
                return RadarAttempt(verdict=RadarVerdict.ALLOW, attempt_id=attempt_id)
            elif verdict_str == "challenge":
                return RadarAttempt(verdict=RadarVerdict.CHALLENGE, attempt_id=attempt_id)
            elif verdict_str == "block":
                return RadarAttempt(verdict=RadarVerdict.BLOCK, attempt_id=attempt_id)
            else:
                logger.warning(
                    "workos_radar_unknown_verdict",
                    verdict=verdict_str,
                    email_hash=_hash_email(email),
                )
                return RadarAttempt(verdict=RadarVerdict.ALLOW, attempt_id=attempt_id)
        else:
            logger.error(
                "workos_radar_api_error",
                status_code=response.status_code,
                response_body=response.text[:500],
                email_hash=_hash_email(email),
            )
            return RadarAttempt(verdict=RadarVerdict.ERROR)

    except requests.exceptions.Timeout:
        logger.warning(
            "workos_radar_timeout",
            email_hash=_hash_email(email),
        )
        return RadarAttempt(verdict=RadarVerdict.ERROR)
    except Exception as e:
        logger.exception(
            "workos_radar_exception",
            email_hash=_hash_email(email),
            error=str(e),
        )
        return RadarAttempt(verdict=RadarVerdict.ERROR)


def send_attempt_success(attempt_id: str, challenge_completed: bool = False) -> None:
    """Raises only when a retry can succeed. A refused report is logged, because a retry gets the same answer."""
    if not _ATTEMPT_ID_PATTERN.fullmatch(attempt_id) or not _is_radar_configured():
        return
    body = {"attempt_status": "success"}
    if challenge_completed:
        body["challenge_status"] = "success"
    response = requests.put(
        f"{WORKOS_RADAR_API_URL}/{attempt_id}",
        headers={
            "Authorization": f"Bearer {settings.WORKOS_RADAR_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=WORKOS_RADAR_TIMEOUT,
    )
    if response.status_code == 429 or response.status_code >= 500:
        raise RadarReportFailed(response.status_code, retry_after=_retry_after_seconds(response))
    if not response.ok:
        logger.warning("workos_radar_success_report_refused", status_code=response.status_code)


def _retry_after_seconds(response: requests.Response) -> Optional[int]:
    value = str(response.headers.get("Retry-After") or "").strip()
    if not value.isdigit():
        return None
    return min(int(value), _MAX_RETRY_AFTER_SECONDS)


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
