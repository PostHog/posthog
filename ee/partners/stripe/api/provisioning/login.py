"""Deep-link login for the Stripe provisioning namespace.

Owns the browser side of the deep-link primitive end to end - the token minted
by ``DeepLinksView`` is consumed only here, under this namespace's own cache
key. Kept separate from the legacy ``/agentic/login`` route so Stripe does not
depend on the provisioning API's login feature.

The token grants a session with no password or SSO challenge, so
partner-asserted email ownership is the only barrier: an explicitly verified
email (``is_email_verified is True``) is required before a session is created.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import login as auth_login
from django.core.cache import cache
from django.http import HttpResponseBase, HttpResponseRedirect

import structlog

from posthog.api.email_verification import EmailVerifier
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.partners.stripe.api.provisioning import DEEP_LINK_CACHE_PREFIX
from ee.partners.stripe.api.provisioning.analytics import capture_provisioning_event
from ee.partners.stripe.api.provisioning.core import is_safe_deep_link_path

logger = structlog.get_logger(__name__)


def _capture(
    outcome: str, *, user_id: int | None = None, team_id: int | None = None, purpose: str | None = None
) -> None:
    capture_provisioning_event("deep_link_login", outcome, user_id=user_id, team_id=team_id, purpose=purpose)


def _redirect_path(team_id: int | None, path: str | None) -> str:
    if path and is_safe_deep_link_path(path):
        return path
    if path:
        # Unreachable in normal operation (mint-time validation already ran); a hit here
        # means cache tampering or a mint-side regression.
        logger.warning("stripe_provisioning.login.unsafe_path_in_cache", path=path)
    if team_id and Team.objects.filter(id=team_id).exists():
        return f"/project/{team_id}"
    return "/"


def stripe_provisioning_login(request: Any) -> HttpResponseBase:
    token = request.GET.get("token", "")
    if not token:
        _capture("missing_token")
        logger.warning("stripe_provisioning.login.missing_token")
        return HttpResponseRedirect("/?error=missing_token")

    cache_key = f"{DEEP_LINK_CACHE_PREFIX}{token}"

    try:
        link_data = cache.get(cache_key)
    except Exception:
        capture_exception(additional_properties={"cache_key": cache_key})
        return HttpResponseRedirect("/?error=service_unavailable")

    if link_data is None:
        _capture("expired_or_invalid_token")
        logger.warning("stripe_provisioning.login.expired_or_invalid_token")
        return HttpResponseRedirect("/?error=expired_or_invalid_token")

    # Atomic delete: if another request already consumed this token, reject.
    if not cache.delete(cache_key):
        _capture("expired_or_invalid_token")
        logger.warning("stripe_provisioning.login.token_already_consumed")
        return HttpResponseRedirect("/?error=expired_or_invalid_token")

    if not isinstance(link_data, dict):
        _capture("invalid_token_data")
        logger.warning("stripe_provisioning.login.invalid_token_data")
        return HttpResponseRedirect("/?error=invalid_token_data")

    user_id = link_data.get("user_id")
    team_id = link_data.get("team_id")
    purpose = link_data.get("purpose", "dashboard")
    path = link_data.get("path")

    if not user_id:
        _capture("invalid_token_data")
        logger.warning("stripe_provisioning.login.missing_user_id")
        return HttpResponseRedirect("/?error=invalid_token_data")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        _capture("user_not_found", user_id=user_id)
        capture_exception(Exception("Deep link login user not found"), {"user_id": user_id, "team_id": team_id})
        return HttpResponseRedirect("/?error=user_not_found")

    if not user.is_active:
        _capture("user_inactive", user_id=user_id)
        logger.warning("stripe_provisioning.login.user_inactive", user_id=user_id)
        return HttpResponseRedirect("/?error=user_inactive")

    # Deep-link login has no password challenge and no SSO step, so partner-asserted
    # email ownership is the only thing standing between an attacker and a session.
    # Require explicit is_email_verified=True - don't trust the legacy None passthrough
    # or the org-level email-verification-disabled flag.
    if user.is_email_verified is not True:
        try:
            EmailVerifier.create_token_and_send_email_verification(user)
        except Exception:
            # Intentionally swallowed: the login must stay blocked regardless of email delivery.
            # EmailVerifier captures the exception internally; the verify_email page has a resend button.
            logger.warning("stripe_provisioning.login.verification_email_failed", user_id=user.id)
        _capture("email_unverified", user_id=user_id)
        logger.warning("stripe_provisioning.login.email_unverified", user_id=user_id)
        return HttpResponseRedirect(f"/verify_email/{user.uuid}")

    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    _capture("success", user_id=user_id, team_id=team_id, purpose=purpose)
    logger.info("stripe_provisioning.login.success", user_id=user_id, team_id=team_id, purpose=purpose)

    return HttpResponseRedirect(_redirect_path(team_id, path))
