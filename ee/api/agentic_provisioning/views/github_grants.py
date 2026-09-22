"""GitHub grants for drop-style partner flows: the partner forwards a GitHub
OAuth code, we exchange and hold the user tokens server-side, and the partner
only ever sees an opaque grant_id. No region proxy: grants are region-local
(the partner must call the region that minted the grant).

Grant creation is charged automatically but the capability refusal is in the
budget's refund set, so a partner without ``can_create_accounts`` still spends
nothing on requests it can never complete.
"""

from __future__ import annotations

from typing import cast

import requests
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.integration import GitHubIntegration
from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning import github_grants
from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.ratelimits import FLAT_MULTIPLIERS, rate_limited
from ee.api.agentic_provisioning.serializers import GitHubGrantCreateSerializer
from ee.api.agentic_provisioning.views.base import GitHubGrantsAPIView


class GitHubGrantsCreateView(GitHubGrantsAPIView):
    @rate_limited("github_grants")
    def post(self, request: Request) -> Response:
        partner = cast(OAuthApplication, request.auth)

        if not partner.provisioning.can_create_accounts:
            capture_provisioning_event("github_grant", "error", partner=partner, error_code="account_creation_disabled")
            raise ProvisioningError("forbidden", "Account creation is not enabled for this partner", status=403)

        data = self.validated_body(GitHubGrantCreateSerializer, request, context={"partner": partner})
        code = data["code"]
        redirect_uri = data["redirect_uri"]

        try:
            authorization = GitHubIntegration.github_user_from_code(code, redirect_uri=redirect_uri)
        except requests.RequestException:
            # Network failure or a non-JSON GitHub error body raising through .json() — retryable,
            # distinct from a clean "bad code" exchange failure (which returns None below).
            capture_provisioning_event("github_grant", "error", partner=partner, error_code="github_unavailable")
            raise ProvisioningError("github_unavailable", "GitHub request failed", status=502)
        if authorization is None:
            capture_provisioning_event("github_grant", "error", partner=partner, error_code="github_exchange_failed")
            raise ProvisioningError("github_exchange_failed", "Could not exchange the GitHub OAuth code", status=502)

        # A user with no verified email gets a grant with email=null — the partner
        # collects an email inline instead. Only an access refusal (App permission
        # misconfiguration) hard-fails, so it can't masquerade as that user state.
        try:
            email = github_grants.fetch_primary_email(authorization.access_token)
        except github_grants.GitHubEmailAccessDenied:
            capture_provisioning_event("github_grant", "error", partner=partner, error_code="email_unavailable")
            raise ProvisioningError("email_unavailable", "GitHub denied reading the user's email addresses", status=502)
        except requests.RequestException:
            capture_provisioning_event("github_grant", "error", partner=partner, error_code="github_unavailable")
            raise ProvisioningError("github_unavailable", "GitHub request failed", status=502)

        grant = github_grants.create_grant(partner, authorization, email)
        capture_provisioning_event("github_grant", "created", partner=partner, gh_login=grant.gh_login)
        return Response(
            {
                "grant_id": grant.grant_id,
                "gh_login": grant.gh_login,
                "email": grant.email,
                "expires_in": github_grants.GITHUB_GRANT_TTL_SECONDS,
            }
        )


class GitHubGrantRepositoriesView(GitHubGrantsAPIView):
    # Keyed per calling partner and grant id, so polls against an id the caller does
    # not own can only exhaust the caller's own budget. Flat multipliers: how fast a
    # visitor's repo picker polls has nothing to do with the partner's trust tier.
    @rate_limited(
        "grant_repo_polls",
        multipliers=FLAT_MULTIPLIERS,
        key=lambda request, view: str(getattr(view, "kwargs", {}).get("grant_id", "")),
    )
    def get(self, request: Request, grant_id: str) -> Response:
        partner = cast(OAuthApplication, request.auth)

        grant = github_grants.load_grant(grant_id, partner)
        if grant is None:
            raise ProvisioningError("grant_not_found", "Grant not found or expired", status=404)

        try:
            listing = github_grants.list_installations_and_repositories(grant.access_token)
        except requests.RequestException:
            capture_provisioning_event("github_grant", "listing_failed", partner=partner)
            raise ProvisioningError("github_unavailable", "GitHub request failed", status=502)

        return Response({"gh_login": grant.gh_login, **listing})
