from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY
from django.http import HttpRequest, HttpResponseRedirect

from posthog.models import User
from posthog.session.activity import sync_current_session_metadata
from posthog.session.risk import RiskTier, evaluate_session_risk


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


class SessionRiskMiddleware:
    """Evaluates session risk in the request phase. On an effective HIGH tier, flushes the session
    server-side and redirects to login; otherwise continues. All flag gating and report-only
    telemetry live in `evaluate_session_risk` — this only enforces the end action."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        # Kill-switch (on by default, off in the test suite). Gated here rather than in
        # evaluate_session_risk so the per-request feature-flag check doesn't run — and thus can't
        # pollute tests that assert posthoganalytics.feature_enabled call counts — when disabled.
        if not settings.SESSION_RISK_ENABLED:
            return self.get_response(request)
        if isinstance(request.user, User) and BACKEND_SESSION_KEY in request.session:
            if evaluate_session_risk(request) == RiskTier.HIGH:
                request.session.flush()  # kills the shared cookie server-side
                # HttpResponseRedirect (not shortcuts.redirect) — the target is a literal path, so
                # skip reverse-resolution, which would import the whole URLconf on the hot path.
                return HttpResponseRedirect("/login?reason=session_risk")
        return self.get_response(request)
