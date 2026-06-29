from django.contrib.auth import BACKEND_SESSION_KEY
from django.http import HttpRequest

from posthog.models import User
from posthog.session.activity import sync_current_session_metadata


class UserAuthSessionActivityMiddleware:
    """Refreshes display metadata on the current login session's row (see posthog.session.activity)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        response = self.get_response(request)
        # Same gate as KnownLoginDeviceCookieMiddleware: only session-authenticated requests. The
        # helper itself skips impersonation.
        if (
            isinstance(request.user, User)
            and BACKEND_SESSION_KEY in request.session
            and not getattr(response, "streaming", False)
        ):
            sync_current_session_metadata(request)
        return response
