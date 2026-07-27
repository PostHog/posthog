import uuid
import hashlib
from typing import Optional

from django.contrib.auth import BACKEND_SESSION_KEY
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone

from loginas.utils import is_impersonated_session

from posthog.constants import AUTH_BACKEND_KEYS
from posthog.geoip import get_geoip_properties
from posthog.models import User
from posthog.session.models import Session
from posthog.utils import _is_valid_ip_address, get_ip_address, get_short_user_agent

# Fixed, arbitrary namespace for deriving a session's public id. We expose `uuid5(namespace, key)`
# rather than the session key itself so the key — which can revoke a session — is never leaked, while
# the public id stays stable and opaque (the high-entropy key can't be recovered from it).
SESSION_PUBLIC_ID_NAMESPACE = uuid.UUID("d9c8b7a6-5432-4f10-9e8d-7c6b5a4f3e2d")

# Refresh display metadata at most once per window. Throttled via cache (never via the session) so
# the write can't mark the session modified and trigger a save that resets these columns.
METADATA_SYNC_INTERVAL_SECONDS = 5 * 60
_METADATA_SYNC_CACHE_PREFIX = "auth_session_synced:"


def session_public_id(session_key: str) -> uuid.UUID:
    return uuid.uuid5(SESSION_PUBLIC_ID_NAMESPACE, session_key)


def _location_from_ip(ip: Optional[str]) -> Optional[str]:
    properties = get_geoip_properties(ip)
    parts = [properties.get("$geoip_city_name"), properties.get("$geoip_country_name")]
    return ", ".join(part for part in parts if part) or None


def _login_method(request: HttpRequest) -> Optional[str]:
    backend = request.session.get(BACKEND_SESSION_KEY)
    method = AUTH_BACKEND_KEYS.get(backend) if backend else None
    return method if isinstance(method, str) else None


def list_user_sessions(user: User) -> list[Session]:
    """The user's live login sessions, most-recently-active first.

    The row IS the session, so filtering live rows by user is the whole query — there are no stale
    or ghost rows to reconcile. Sessions never refreshed since the swap (NULL last_activity) sort last.
    """
    return list(
        Session.objects.filter(user_id=user.pk, expire_date__gt=timezone.now()).order_by(
            F("last_activity").desc(nulls_last=True)
        )
    )


def sync_current_session_metadata(request: HttpRequest, force: bool = False) -> None:
    """Refresh display metadata (ip, UA, location, last_activity) on the current session row.

    Runs in the activity middleware on every authenticated request. Impersonation sessions are
    skipped — their row carries no `user_id` and must never surface in the impersonated user's list.
    """
    user = request.user
    if not isinstance(user, User) or not user.is_authenticated or user.pk is None:
        return
    if BACKEND_SESSION_KEY not in request.session:
        return
    session_key = request.session.session_key
    if not session_key:
        return
    if is_impersonated_session(request):
        return

    # Key the throttle by a hash of the session key, never the raw key (avoids storing it in cache keys).
    cache_key = f"{_METADATA_SYNC_CACHE_PREFIX}{hashlib.sha256(session_key.encode()).hexdigest()}"
    if not force and cache.get(cache_key):
        return

    ip = get_ip_address(request)
    fields = {
        "last_activity": timezone.now(),
        "ip": ip if _is_valid_ip_address(ip) else None,
        "short_user_agent": get_short_user_agent(request) or None,
        "location": _location_from_ip(ip),
        "login_method": _login_method(request),
    }
    # Note: the risk baseline columns (latitude/longitude/country_code/ua_signature/baseline_at) are
    # NOT written here. They are owned by evaluate_session_risk, which advances them only on low-risk
    # requests so a suspicious request can't overwrite the known-good reference (posthog/session/risk.py).

    # Defer the write to commit. This metadata is best-effort display data, so the write must never
    # add a query to the caller's transaction (which would break assertNumQueries assertions across
    # the suite) nor run against a transaction already broken by a handled IntegrityError. In
    # autocommit (no open transaction) on_commit runs immediately; mark the throttle only once the
    # write actually commits, so a rollback lets the next request retry.
    def _write() -> None:
        Session.objects.filter(session_key=session_key).update(**fields)
        cache.set(cache_key, True, timeout=METADATA_SYNC_INTERVAL_SECONDS)

    transaction.on_commit(_write)


def revoke_other_sessions(user: User, keep_session_key: Optional[str]) -> int:
    """Revoke every login session for `user` except `keep_session_key`. Returns the count revoked."""
    queryset = Session.objects.filter(user_id=user.pk)
    if keep_session_key:
        queryset = queryset.exclude(session_key=keep_session_key)
    count, _ = queryset.delete()
    return count


def revoke_other_sessions_for_request(request: HttpRequest, user: User) -> int:
    """Revoke the user's other login sessions on a credential change, keeping the request's own
    session. No-op while impersonating so staff support never mass-logs-out a customer. Returns the
    count revoked."""
    if is_impersonated_session(request):
        return 0
    return revoke_other_sessions(user, request.session.session_key)


def revoke_user_auth_session(user: User, public_id: str) -> bool:
    """Revoke a single login session owned by `user`, identified by its public id. Self-only.

    Returns False if the id is malformed or doesn't match one of the user's sessions.
    """
    try:
        target = uuid.UUID(str(public_id))
    except (ValueError, AttributeError, TypeError):
        return False
    # The public id is a one-way derivation of the key, so match by recomputing over the user's own
    # (small) set of sessions rather than querying it directly.
    for session_key in Session.objects.filter(user_id=user.pk).values_list("session_key", flat=True):
        if session_public_id(session_key) == target:
            Session.objects.filter(user_id=user.pk, session_key=session_key).delete()
            return True
    return False
