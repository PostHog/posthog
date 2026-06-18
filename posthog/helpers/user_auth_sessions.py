import time
from typing import Optional

from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.utils import timezone

from loginas.utils import is_impersonated_session

from posthog.constants import AUTH_BACKEND_KEYS
from posthog.geoip import get_geoip_properties
from posthog.models import User, UserAuthSession
from posthog.utils import _is_valid_ip_address, get_ip_address, get_short_user_agent

# Throttle window for refreshing `last_activity` so we don't write to the DB on every request.
AUTH_SESSION_SYNC_INTERVAL_SECONDS = 5 * 60
# Session key holding the timestamp of the last index write, used to enforce the throttle.
AUTH_SESSION_SYNCED_AT_KEY = "auth_session_synced_at"

_MAX_USER_AGENT_LENGTH = 1024


def _location_from_ip(ip: Optional[str]) -> Optional[str]:
    properties = get_geoip_properties(ip)
    parts = [properties.get("$geoip_city_name"), properties.get("$geoip_country_name")]
    return ", ".join(part for part in parts if part) or None


def _login_method(request: HttpRequest) -> Optional[str]:
    backend = request.session.get(BACKEND_SESSION_KEY)
    method = AUTH_BACKEND_KEYS.get(backend) if backend else None
    return method if isinstance(method, str) else None


def sync_user_auth_session(request: HttpRequest) -> None:
    """Upsert the current request's login session into the index, throttled to one write per window.

    Runs in the activity middleware on every authenticated request. Impersonation sessions are never
    recorded — a staff member impersonating a customer must not surface in the customer's own list.
    """
    user = request.user
    if not isinstance(user, User) or not user.is_authenticated:
        return
    # A user that deleted their own account earlier in this request has no pk; skip rather than
    # try to write a row referencing a now-unsaved user.
    if user.pk is None:
        return
    if BACKEND_SESSION_KEY not in request.session:
        return

    session_key = request.session.session_key
    if not session_key:
        return

    if is_impersonated_session(request):
        UserAuthSession.objects.filter(session_key=session_key).delete()
        return

    now = time.time()
    last_synced = request.session.get(AUTH_SESSION_SYNCED_AT_KEY)
    if last_synced and now - last_synced < AUTH_SESSION_SYNC_INTERVAL_SECONDS:
        return

    ip = get_ip_address(request)
    raw_user_agent = request.headers.get("user-agent") or None
    UserAuthSession.objects.update_or_create(
        session_key=session_key,
        user=user,
        defaults={
            "last_activity": timezone.now(),
            "ip": ip if _is_valid_ip_address(ip) else None,
            "user_agent": raw_user_agent[:_MAX_USER_AGENT_LENGTH] if raw_user_agent else None,
            "short_user_agent": get_short_user_agent(request) or None,
            "location": _location_from_ip(ip),
            "login_method": _login_method(request),
        },
    )
    request.session[AUTH_SESSION_SYNCED_AT_KEY] = now


def delete_current_auth_session(request: HttpRequest) -> None:
    """Remove the index row for the request's session — used on logout (the django_session row is
    flushed by `auth.logout`, but the index row would otherwise linger until the GC sweep)."""
    session = getattr(request, "session", None)
    session_key = getattr(session, "session_key", None)
    if session_key:
        UserAuthSession.objects.filter(session_key=session_key).delete()


def _delete_sessions(session_keys: list[str]) -> None:
    if not session_keys:
        return
    Session.objects.filter(session_key__in=session_keys).delete()
    UserAuthSession.objects.filter(session_key__in=session_keys).delete()


def revoke_other_sessions(user: User, keep_session_key: Optional[str]) -> int:
    """Revoke every login session for `user` except `keep_session_key`. Returns the count revoked."""
    queryset = UserAuthSession.objects.filter(user=user)
    if keep_session_key:
        queryset = queryset.exclude(session_key=keep_session_key)
    session_keys = list(queryset.values_list("session_key", flat=True))
    _delete_sessions(session_keys)
    return len(session_keys)


def revoke_user_auth_session(user: User, session_id: str) -> bool:
    """Revoke a single login session owned by `user`. Returns False if it doesn't exist or isn't theirs."""
    try:
        row = UserAuthSession.objects.get(user=user, id=session_id)
    except (UserAuthSession.DoesNotExist, ValidationError, ValueError):
        # ValidationError/ValueError: session_id wasn't a valid UUID — treat as not found.
        return False
    _delete_sessions([row.session_key])
    return True
