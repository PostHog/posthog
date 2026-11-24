"""Reports a password login to WorkOS Radar when the session signs in, which is after any second factor."""

import time
import hashlib
from typing import Any, Optional

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.auth.signals import user_logged_in
from django.core.cache import caches
from django.db import transaction
from django.dispatch import receiver
from django.http import HttpRequest

import structlog

logger = structlog.get_logger(__name__)

RADAR_LOGIN_ATTEMPT_SESSION_KEY = "radar_login_attempt"
RADAR_LOGIN_ATTEMPT_CACHE_ALIAS = "radar_login_attempt"
_REQUEST_ATTRIBUTE = "_radar_login_attempt"
# The password form and every second factor after it sign in with this backend; a passkey or SSO login does not
_PASSWORD_FLOW_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _pending_ttl_seconds() -> int:
    return int(getattr(settings, "TWO_FACTOR_LOGIN_TIMEOUT", 600))


def _cache_key(session_key: str) -> str:
    return f"radar_login_attempt:{hashlib.sha256(session_key.encode()).hexdigest()}"


def remember_login_attempt(request: HttpRequest, attempt_id: str, user_pk: int, valid_for_seconds: int) -> None:
    """Keep the attempt of a correct password until the session signs in as that user."""
    _store_pending(request, {"attempt_id": attempt_id, "user_pk": user_pk}, valid_for_seconds)


def extend_login_attempt(request: HttpRequest, valid_for_seconds: int) -> None:
    """Keep a pending attempt for as long as the login code sent now stays valid."""
    pending = request.session.get(RADAR_LOGIN_ATTEMPT_SESSION_KEY)
    if isinstance(pending, dict):
        _store_pending(request, pending, valid_for_seconds)


def _store_pending(request: HttpRequest, pending: dict[str, Any], valid_for_seconds: int) -> None:
    ttl_seconds = max(valid_for_seconds, _pending_ttl_seconds())
    pending = {**pending, "expires_at": time.time() + ttl_seconds}
    request.session[RADAR_LOGIN_ATTEMPT_SESSION_KEY] = pending
    # login() flushes a session signed in as another account, so these copies carry the attempt past it
    setattr(request, _REQUEST_ATTRIBUTE, pending)
    if SESSION_KEY in request.session and request.session.session_key:
        try:
            caches[RADAR_LOGIN_ATTEMPT_CACHE_ALIAS].set(
                _cache_key(request.session.session_key), pending, timeout=ttl_seconds
            )
        except Exception:
            logger.warning("workos_radar_login_attempt_not_cached", exc_info=True)


def _take_pending(request: HttpRequest) -> Optional[dict[str, Any]]:
    for candidate in (
        request.session.pop(RADAR_LOGIN_ATTEMPT_SESSION_KEY, None),
        getattr(request, _REQUEST_ATTRIBUTE, None),
    ):
        if isinstance(candidate, dict):
            return candidate
    incoming_session_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    if not incoming_session_key:
        return None
    # The report is optional, so a cache outage must not fail the login that fires this signal
    try:
        attempt_cache = caches[RADAR_LOGIN_ATTEMPT_CACHE_ALIAS]
        candidate = attempt_cache.get(_cache_key(incoming_session_key))
        attempt_cache.delete(_cache_key(incoming_session_key))
    except Exception:
        logger.warning("workos_radar_login_attempt_cache_unavailable", exc_info=True)
        return None
    return candidate if isinstance(candidate, dict) else None


@receiver(user_logged_in)
def report_radar_login_success(sender: Any, user: Any, request: Optional[HttpRequest] = None, **kwargs: Any) -> None:
    if request is None or getattr(request, "session", None) is None:
        return
    if request.session.get(BACKEND_SESSION_KEY) != _PASSWORD_FLOW_BACKEND:
        # A passkey or SSO login drops the attempt without a cache round trip
        request.session.pop(RADAR_LOGIN_ATTEMPT_SESSION_KEY, None)
        return
    pending = _take_pending(request)
    if pending is None or pending.get("user_pk") != user.pk:
        return
    if time.time() > float(pending.get("expires_at") or 0):
        return
    attempt_id = str(pending.get("attempt_id") or "")
    # posthog.tasks imports every task module, so it loads at a login that has an attempt, not at startup
    from posthog.tasks.workos_radar import queue_attempt_success  # noqa: PLC0415

    # The second-factor views sign in inside a transaction, so the report waits for the commit
    transaction.on_commit(lambda: queue_attempt_success(attempt_id))
