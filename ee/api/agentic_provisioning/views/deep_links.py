"""Deep links: POST /provisioning/deep_links mints a single-use login URL for
the partner's user; GET /agentic/login consumes it and mints a session."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any, cast

from django.contrib.auth import login as auth_login
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

import structlog
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.email_verification import EmailVerifier
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthAccessToken
from posthog.models.oauth_provisioning import PartnerTier
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.api.agentic_provisioning.analytics import capture_deep_link_event, capture_provisioning_event
from ee.api.agentic_provisioning.constants import (
    DEEP_LINK_CACHE_PREFIX,
    DEEP_LINK_DISALLOWED_PATH_CHARS,
    DEEP_LINK_MAX_PATH_LENGTH,
    DEEP_LINK_TTL_SECONDS,
)
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.ratelimits import BLOCKED, rate_limited
from ee.api.agentic_provisioning.regions import current_region_host
from ee.api.agentic_provisioning.serializers import DeepLinkSerializer
from ee.api.agentic_provisioning.views.base import BearerResourceAPIView

logger = structlog.get_logger(__name__)


def is_safe_deep_link_path(path: object) -> bool:
    """Allow only relative, same-origin in-app paths so a deep link can't become an open redirect."""
    return (
        isinstance(path, str)
        and 0 < len(path) <= DEEP_LINK_MAX_PATH_LENGTH
        # Reject control chars, whitespace, and backslashes (the `/\` backslash-host form included).
        and not DEEP_LINK_DISALLOWED_PATH_CHARS.search(path)
        and path.startswith("/")
        # Reject protocol-relative (`//`) forms; a single leading `/` keeps it same-origin.
        and not path.startswith("//")
        and url_has_allowed_host_and_scheme(path, allowed_hosts=None)
    )


class DeepLinksView(BearerResourceAPIView):
    # A deep link mints a full web session, so on top of the admin-granted
    # capability the public tiers get no budget at all: a client identified only
    # by a client_id anyone can send has no business minting sessions. An
    # explicit per-partner override outranks BLOCKED if one is ever needed.
    @rate_limited(
        "deep_links",
        multipliers={PartnerTier.PUBLIC: BLOCKED, PartnerTier.PUBLIC_ATTESTED: BLOCKED},
    )
    def post(self, request: Request) -> Response:
        access_token = cast(OAuthAccessToken, request.auth)

        if not access_token.application.provisioning.can_issue_deep_links:
            capture_provisioning_event("deep_link_created", "not_enabled", partner=access_token.application)
            raise ProvisioningError(
                "deep_links_not_enabled",
                "Deep links are not enabled for this partner",
                status=403,
            )

        data = self.validated_body(DeepLinkSerializer, request)

        # `purpose` is a free-form label retained for analytics. `path` is the generic
        # destination: any in-app path the partner wants the user to land on after login.
        purpose = data["purpose"]
        path = data["path"]
        if path and not is_safe_deep_link_path(path):
            capture_provisioning_event(
                "deep_link_created", "invalid_path", partner=access_token.application, purpose=purpose
            )
            raise ProvisioningError(
                "invalid_path",
                "path must be a relative in-app path beginning with a single '/'",
                status=400,
            )

        scoped_teams = access_token.scoped_teams or []
        team_id = scoped_teams[0] if scoped_teams else None

        host = current_region_host()

        token = secrets.token_urlsafe(32)
        cache_key = f"{DEEP_LINK_CACHE_PREFIX}{token}"
        cache.set(
            cache_key,
            {
                "user_id": access_token.user_id,
                "team_id": team_id,
                "purpose": purpose,
                "path": path or None,
            },
            timeout=DEEP_LINK_TTL_SECONDS,
        )

        expires_at = timezone.now() + timedelta(seconds=DEEP_LINK_TTL_SECONDS)

        url = f"{host}/agentic/login?token={token}"
        if team_id:
            url += f"&team_id={team_id}"

        capture_provisioning_event(
            "deep_link_created", "success", partner=access_token.application, purpose=purpose, team_id=team_id
        )

        return Response(
            {
                "purpose": purpose,
                "url": url,
                "expires_at": expires_at.isoformat(),
            }
        )


def agentic_login(request: Any) -> HttpResponseBase:
    """GET /agentic/login — deep link login for agentic provisioning users."""
    token = request.GET.get("token", "")
    if not token:
        capture_deep_link_event("missing_token")
        logger.warning("agentic_login.missing_token")
        return HttpResponseRedirect("/?error=missing_token")

    cache_key = f"{DEEP_LINK_CACHE_PREFIX}{token}"

    try:
        link_data = cache.get(cache_key)
    except Exception:
        capture_exception(additional_properties={"cache_key": cache_key})
        return HttpResponseRedirect("/?error=service_unavailable")

    if link_data is None:
        capture_deep_link_event("expired_or_invalid_token")
        logger.warning("agentic_login.expired_or_invalid_token")
        return HttpResponseRedirect("/?error=expired_or_invalid_token")

    # Atomic delete — if another request already consumed this token, reject
    if not cache.delete(cache_key):
        capture_deep_link_event("expired_or_invalid_token")
        logger.warning("agentic_login.token_already_consumed")
        return HttpResponseRedirect("/?error=expired_or_invalid_token")

    if not isinstance(link_data, dict):
        capture_deep_link_event("invalid_token_data")
        logger.warning("agentic_login.invalid_token_data")
        return HttpResponseRedirect("/?error=invalid_token_data")

    user_id = link_data.get("user_id")
    team_id = link_data.get("team_id")
    purpose = link_data.get("purpose", "dashboard")
    path = link_data.get("path")

    if not user_id:
        capture_deep_link_event("invalid_token_data")
        logger.warning("agentic_login.missing_user_id")
        return HttpResponseRedirect("/?error=invalid_token_data")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        capture_deep_link_event("user_not_found", user_id=user_id)
        capture_exception(
            Exception("Deep link login user not found"),
            {"user_id": user_id, "team_id": team_id},
        )
        return HttpResponseRedirect("/?error=user_not_found")

    if not user.is_active:
        capture_deep_link_event("user_inactive", user_id=user_id)
        logger.warning("agentic_login.user_inactive", user_id=user_id)
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
            logger.warning("agentic_login.verification_email_failed", user_id=user.id)
        capture_deep_link_event("email_unverified", user_id=user_id)
        logger.warning("agentic_login.email_unverified", user_id=user_id)
        return HttpResponseRedirect(f"/verify_email/{user.uuid}")

    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    capture_deep_link_event("success", user_id=user_id, team_id=team_id, purpose=purpose)
    logger.info("agentic_login.success", user_id=user_id, team_id=team_id, purpose=purpose)

    redirect_path = _deep_link_redirect_path(purpose, team_id, path)
    return HttpResponseRedirect(redirect_path)


def _deep_link_redirect_path(purpose: str, team_id: int | None, path: str | None = None) -> str:
    if path and is_safe_deep_link_path(path):
        return path
    if path:
        # Unreachable in normal operation (mint-time validation already ran); a hit here means
        # cache tampering or a mint-side regression.
        logger.warning("agentic_login.unsafe_path_in_cache", path=path)
    if team_id and Team.objects.filter(id=team_id).exists():
        return f"/project/{team_id}"
    return "/"
