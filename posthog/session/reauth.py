import time
from typing import Optional

from django.conf import settings
from django.contrib.sessions.backends.base import SessionBase


def sensitive_action_reference(session: SessionBase) -> Optional[float]:
    """Start of the sensitive-action freshness window: the most recent of session creation or the
    last step-up re-auth. None when neither is set (the middleware should always stamp creation).

    Single source of truth so the permission check and the API-reported expiry can't disagree.
    """
    session_created_at = session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)
    last_reauth_at = session.get(settings.SESSION_LAST_REAUTH_AT_KEY)
    reference = max(session_created_at or 0.0, last_reauth_at or 0.0)
    return reference or None


def step_up_required(session: SessionBase) -> bool:
    """Whether a risk anomaly flagged this session as needing a fresh re-auth before sensitive actions."""
    return bool(session.get(settings.SESSION_STEP_UP_REQUIRED_KEY))


def sensitive_window_is_open(session: SessionBase) -> bool:
    """Whether the last sign-in or re-auth is within `SESSION_SENSITIVE_ACTIONS_AGE`. Ignores a risk step-up."""
    reference = sensitive_action_reference(session)
    return reference is not None and time.time() - reference <= settings.SESSION_SENSITIVE_ACTIONS_AGE


def session_allows_sensitive_actions(session: SessionBase) -> bool:
    """Whether this session may make a sensitive write, such as minting a lasting credential, without a re-auth."""
    return not step_up_required(session) and sensitive_window_is_open(session)


def fresh_reauth_expires_at(session: SessionBase) -> Optional[float]:
    """End of the short window that an identity change needs, counted from the last re-auth alone.

    Session creation does not count here, unlike in `sensitive_action_reference`: a login stamps both
    keys, so a fresh login still passes, but an old session cannot.
    """
    last_reauth_at = session.get(settings.SESSION_LAST_REAUTH_AT_KEY)
    if not last_reauth_at:
        return None
    return last_reauth_at + settings.SESSION_FRESH_REAUTH_AGE


def reauth_is_fresh(session: SessionBase) -> bool:
    expires_at = fresh_reauth_expires_at(session)
    return expires_at is not None and time.time() < expires_at and not step_up_required(session)
