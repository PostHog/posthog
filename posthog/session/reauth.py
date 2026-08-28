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
