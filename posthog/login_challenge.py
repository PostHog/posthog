"""Turnstile check on password login from new browsers.

In shadow mode the check records what the browser sent and never changes the login result.
"""

import hashlib
from enum import StrEnum

from django.conf import settings
from django.http import HttpRequest

import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram

from posthog.helpers.user_devices import has_valid_known_device_cookie
from posthog.models import User
from posthog.models.instance_setting import get_instance_setting
from posthog.turnstile import SiteverifyOutcome, SiteverifyResult, verify_login_turnstile_token
from posthog.utils import get_short_user_agent, get_trusted_client_ip

logger = structlog.get_logger(__name__)

DECISIONS_COUNTER = Counter(
    "posthog_login_turnstile_decisions_total",
    "Turnstile outcomes recorded for password logins, by mode, outcome and what the browser reported",
    labelnames=["mode", "outcome", "client_status"],
)
SITEVERIFY_SECONDS = Histogram(
    "posthog_login_turnstile_siteverify_seconds",
    "Time the login path spent on Cloudflare siteverify, by result",
    labelnames=["result"],
)


class LoginTurnstileMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"


class LoginTurnstileOutcome(StrEnum):
    SKIPPED_REAUTH = "skipped_reauth"
    SKIPPED_KNOWN_DEVICE = "skipped_known_device"
    NO_TOKEN = "no_token"
    PASSED = "passed"
    REJECTED = "rejected"
    VERIFY_UNAVAILABLE = "verify_unavailable"
    ERROR = "error"


class TurnstileClientStatus(StrEnum):
    TOKEN = "token"
    PENDING = "pending"
    ERROR = "error"
    EXPIRED = "expired"
    UNSUPPORTED = "unsupported"
    SCRIPT_FAILED = "script_failed"
    NOT_RENDERED = "not_rendered"
    UNKNOWN = "unknown"
    ABSENT = "absent"


_OUTCOME_BY_SITEVERIFY_RESULT = {
    SiteverifyResult.ACCEPTED: LoginTurnstileOutcome.PASSED,
    SiteverifyResult.REJECTED: LoginTurnstileOutcome.REJECTED,
    SiteverifyResult.UNAVAILABLE: LoginTurnstileOutcome.VERIFY_UNAVAILABLE,
}


def get_login_turnstile_mode() -> LoginTurnstileMode:
    value = str(get_instance_setting("LOGIN_TURNSTILE_MODE") or "").strip().lower()
    try:
        return LoginTurnstileMode(value)
    except ValueError:
        return LoginTurnstileMode.OFF


def is_login_turnstile_active() -> bool:
    return (
        get_login_turnstile_mode() == LoginTurnstileMode.SHADOW
        and bool(settings.CLOUDFLARE_TURNSTILE_SITE_KEY)
        and bool(settings.CLOUDFLARE_TURNSTILE_SECRET_KEY)
    )


def _is_known_device(request: HttpRequest, user: User | None) -> bool:
    return user is not None and has_valid_known_device_cookie(request, user)


def precheck_turnstile_fields(request: HttpRequest, user: User | None) -> dict[str, str]:
    # An email with no account gets the same answer as an account without the cookie, so the
    # site key does not tell a caller whether the account exists.
    try:
        if not is_login_turnstile_active() or _is_known_device(request, user):
            return {}
        return {"turnstile_site_key": settings.CLOUDFLARE_TURNSTILE_SITE_KEY}
    except Exception:
        logger.exception("login_turnstile_precheck_failed")
        return {}


def record_login_turnstile_decision(
    request: HttpRequest,
    *,
    email: str,
    existing_user: User | None,
    is_reauth: bool,
    token: str,
    client_status: str,
) -> LoginTurnstileOutcome | None:
    try:
        if not is_login_turnstile_active():
            return None
    except Exception:
        logger.exception("login_turnstile_mode_read_failed")
        return None

    normalized_status = _normalize_client_status(client_status)
    siteverify: SiteverifyOutcome | None = None
    try:
        outcome, siteverify = _decide(request, existing_user=existing_user, is_reauth=is_reauth, token=token)
    except Exception:
        logger.exception("login_turnstile_decision_failed")
        outcome = LoginTurnstileOutcome.ERROR

    try:
        _emit(
            request,
            outcome=outcome,
            client_status=normalized_status,
            email=email,
            existing_user=existing_user,
            siteverify=siteverify,
        )
    except Exception:
        logger.exception("login_turnstile_emit_failed")
    return outcome


def _normalize_client_status(value: str) -> TurnstileClientStatus:
    if not value:
        return TurnstileClientStatus.ABSENT
    try:
        return TurnstileClientStatus(value)
    except ValueError:
        return TurnstileClientStatus.UNKNOWN


def _decide(
    request: HttpRequest, *, existing_user: User | None, is_reauth: bool, token: str
) -> tuple[LoginTurnstileOutcome, SiteverifyOutcome | None]:
    if is_reauth:
        return LoginTurnstileOutcome.SKIPPED_REAUTH, None
    if _is_known_device(request, existing_user):
        return LoginTurnstileOutcome.SKIPPED_KNOWN_DEVICE, None
    if not token:
        return LoginTurnstileOutcome.NO_TOKEN, None
    siteverify = verify_login_turnstile_token(token, get_trusted_client_ip(request) or "")
    return _OUTCOME_BY_SITEVERIFY_RESULT[siteverify.result], siteverify


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _emit(
    request: HttpRequest,
    *,
    outcome: LoginTurnstileOutcome,
    client_status: TurnstileClientStatus,
    email: str,
    existing_user: User | None,
    siteverify: SiteverifyOutcome | None,
) -> None:
    mode = LoginTurnstileMode.SHADOW
    DECISIONS_COUNTER.labels(mode=mode, outcome=outcome, client_status=client_status).inc()

    email_hash = _hash(email.lower())
    properties: dict[str, object] = {
        "mode": mode.value,
        "outcome": outcome.value,
        "client_status": client_status.value,
        "has_account": existing_user is not None,
        "ip_address_hash": _hash(get_trusted_client_ip(request) or ""),
        "user_agent": get_short_user_agent(request),
        "email_domain": email.split("@")[-1] if "@" in email else "",
    }
    # A token over the length limit is rejected without a call, so its duration is zero.
    if siteverify is not None and siteverify.duration_seconds > 0:
        SITEVERIFY_SECONDS.labels(result=siteverify.result).observe(siteverify.duration_seconds)
        properties["siteverify_duration_ms"] = round(siteverify.duration_seconds * 1000, 2)
    if outcome == LoginTurnstileOutcome.REJECTED and siteverify is not None:
        properties["turnstile_error_codes"] = list(siteverify.error_codes)

    distinct_id = (existing_user.distinct_id if existing_user else None) or f"pre_login_{email_hash}"
    posthoganalytics.capture(distinct_id=distinct_id, event="login_turnstile_decision", properties=properties)
    logger.info("login_turnstile_decision", email_hash=email_hash, **properties)
