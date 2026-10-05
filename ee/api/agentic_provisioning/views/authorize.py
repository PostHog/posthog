"""Interactive OAuth consent for existing users.

The orchestrator redirects the user to GET /api/agentic/authorize; on approval
(automatic for trusted partners, via the in-app consent page otherwise) we
issue an auth code and redirect back to the orchestrator callback. The
pending/confirm endpoints back the in-app consent page, so unlike the rest of
this package they authenticate the browser session and speak the frontend's
plain error shapes, not the partner envelopes.
"""

from __future__ import annotations

import re
from typing import Any, cast
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.http.response import HttpResponseBase

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.oauth import OAuthApplication
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.api.agentic_provisioning.accounts import (
    find_partner_organization_team,
    get_callback_url,
    get_or_create_partner_organization_team,
    mint_pending_auth_code,
    resolve_pending_partner,
)
from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.constants import PENDING_AUTH_CACHE_PREFIX, SAFE_STATE_RE
from ee.api.agentic_provisioning.tokens import user_can_access_team


def _sanitize_state(state: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "", state)


def _partner_deactivated_redirect(pending_key: str) -> HttpResponseRedirect:
    cache.delete(pending_key)
    capture_provisioning_event("authorize", "partner_deactivated")
    return HttpResponseRedirect(f"{settings.SITE_URL}?error=partner_deactivated")


def _consent_page_redirect(state: str) -> HttpResponseRedirect:
    capture_provisioning_event("authorize", "selection_required")

    base = settings.SITE_URL.rstrip("/")
    params = urlencode({"state": _sanitize_state(state)})
    return HttpResponseRedirect(f"{base}/agentic/authorize?{params}")


def _paying_partner(partner: OAuthApplication | None) -> OAuthApplication | None:
    return partner if partner is not None and partner.provisioning.pays_for_customers else None


@login_required
def agentic_authorize(request: Any) -> HttpResponseBase:
    state = request.GET.get("state", "")
    if not state or not SAFE_STATE_RE.match(state):
        capture_provisioning_event("authorize", "missing_state")
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=missing_state")

    pending_key = f"{PENDING_AUTH_CACHE_PREFIX}{state}"
    pending = cache.get(pending_key)
    if pending is None:
        capture_provisioning_event("authorize", "expired_state")
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=expired_or_invalid_state")

    if request.user.email != pending["email"]:
        capture_provisioning_event("authorize", "email_mismatch")
        mismatch_params = urlencode(
            {
                "expected_email": pending["email"],
                "current_email": request.user.email,
                "partner_name": pending.get("partner_name", ""),
                "state": state,
            }
        )
        return HttpResponseRedirect(f"{settings.SITE_URL.rstrip('/')}/agentic/account-mismatch?{mismatch_params}")

    user = request.user
    memberships = list(user.organization_memberships.select_related("organization").all())
    if not memberships:
        capture_provisioning_event("authorize", "no_organization")
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=no_organization")

    partner_app = resolve_pending_partner(pending.get("partner_id", ""))
    paying_partner = _paying_partner(partner_app)
    if paying_partner is not None:
        # The confirm step puts this partner's project in an organization the partner pays
        # for, so no project of the user's is created, picked, or auto-approved here.
        if not paying_partner.provisioning.active:
            return _partner_deactivated_redirect(pending_key)
        return _consent_page_redirect(state)

    # Only teams the user can actually reach are eligible: the auto-approve path
    # below mints a code for non_demo_teams[0] without further checks.
    org_ids = [m.organization_id for m in memberships]
    non_demo_teams = [
        team
        for team in Team.objects.filter(organization_id__in=org_ids, is_demo=False)
        if user_can_access_team(user, team)
    ]

    if not non_demo_teams:
        organization = memberships[0].organization
        team = Team.objects.create_with_data(initiating_user=user, organization=organization)
        non_demo_teams = [team]
        capture_provisioning_event("authorize", "auto_created_project", team_id=team.id)

    # Re-check partner is still active (could have been deactivated since account_requests)
    is_trusted_partner = False
    if partner_app is not None:
        if not partner_app.provisioning.active:
            return _partner_deactivated_redirect(pending_key)
        # Fail closed: a partner-identified pending state missing the flag (e.g. created by an
        # older pod mid-deploy) must still require consent, never silently auto-approve.
        is_trusted_partner = partner_app.provisioning.skip_existing_user_consent and not pending.get(
            "consent_required", True
        )

    if is_trusted_partner and len(memberships) == 1 and len(non_demo_teams) == 1:
        organization = memberships[0].organization
        team = non_demo_teams[0]

        callback_url = get_callback_url(partner_app)
        if callback_url is None:
            capture_provisioning_event("authorize", "missing_callback")
            return HttpResponseRedirect(f"{settings.SITE_URL}?error=missing_callback")

        code = mint_pending_auth_code(pending, user_id=user.id, org_id=str(organization.id), team_id=team.id)
        cache.delete(pending_key)

        capture_provisioning_event("authorize", "auto_redirect", team_id=team.id)

        params = urlencode({"code": code, "state": _sanitize_state(state)})
        return HttpResponseRedirect(f"{callback_url}?{params}")

    return _consent_page_redirect(state)


class AuthorizePendingView(APIView):
    """Return server-verified partner name, scopes and billing for a pending auth state.

    The frontend calls this instead of reading from URL params, preventing
    an attacker from spoofing the partner identity on the consent page.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        state = request.query_params.get("state", "")
        if not state or not SAFE_STATE_RE.match(state):
            return Response({"error": "invalid_state"}, status=400)

        pending = cache.get(f"{PENDING_AUTH_CACHE_PREFIX}{state}")
        if pending is None:
            return Response({"error": "expired_or_invalid_state"}, status=400)

        user = cast(User, request.user)
        if user.email != pending["email"]:
            return Response({"error": "email_mismatch"}, status=403)

        paying_partner = _paying_partner(resolve_pending_partner(pending.get("partner_id", "")))
        partner_team = find_partner_organization_team(user, paying_partner) if paying_partner is not None else None

        return Response(
            {
                "partner_name": pending.get("partner_name", "the requesting app"),
                "scopes": pending.get("scopes", []),
                "pays_for_customers": paying_partner is not None,
                "partner_organization_name": partner_team.organization.name if partner_team is not None else None,
            }
        )


class AuthorizeConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        state = request.data.get("state", "")
        if not state or not SAFE_STATE_RE.match(state):
            capture_provisioning_event("authorize_confirm", "invalid_request")
            return Response({"error": "state and team_id are required"}, status=400)

        pending_key = f"{PENDING_AUTH_CACHE_PREFIX}{state}"
        pending = cache.get(pending_key)
        confirm_partner = resolve_pending_partner(pending.get("partner_id", "")) if pending is not None else None
        paying_partner = _paying_partner(confirm_partner)

        # A paying partner's consent page has no project picker, so it sends no team_id, and
        # a team_id sent anyway is ignored.
        team_id = request.data.get("team_id")
        if team_id is None and paying_partner is None:
            capture_provisioning_event("authorize_confirm", "invalid_request")
            return Response({"error": "state and team_id are required"}, status=400)

        if pending is None:
            capture_provisioning_event("authorize_confirm", "expired_state")
            return Response({"error": "expired_or_invalid_state"}, status=400)

        user = cast(User, request.user)

        if user.email != pending["email"]:
            capture_provisioning_event("authorize_confirm", "email_mismatch")
            return Response({"error": "email_mismatch"}, status=403)

        if paying_partner is None:
            try:
                team = Team.objects.get(id=team_id, is_demo=False)
            except Team.DoesNotExist:
                capture_provisioning_event("authorize_confirm", "team_not_found", team_id=team_id)
                return Response({"error": "team_not_found"}, status=404)

            # The user picks the team here, so consent does not imply access: check
            # team level too, or an org member excluded from a private project could
            # approve a code scoped to it.
            in_org = user.organization_memberships.filter(organization_id=team.organization_id).exists()
            if not in_org or not user_can_access_team(user, team):
                capture_provisioning_event("authorize_confirm", "team_not_accessible", team_id=team_id)
                return Response({"error": "team_not_accessible"}, status=403)

        if confirm_partner is not None and not confirm_partner.provisioning.active:
            cache.delete(pending_key)
            capture_provisioning_event("authorize_confirm", "partner_deactivated", partner=confirm_partner)
            return Response({"error": "partner_deactivated"}, status=403)

        callback_url = get_callback_url(confirm_partner)
        if callback_url is None:
            capture_provisioning_event("authorize_confirm", "missing_callback", partner=confirm_partner)
            return Response({"error": "missing_callback"}, status=400)

        success_properties: dict[str, object] = {}
        if paying_partner is not None:
            # Resolved only once every check above has passed, so a refused confirm leaves no
            # organization behind.
            team, created = get_or_create_partner_organization_team(user, paying_partner)
            success_properties["partner_organization"] = "created" if created else "reused"

        # Mint the auth code BEFORE deleting pending state so a cache hiccup
        # between the two doesn't leave the user with no recovery path.
        code = mint_pending_auth_code(pending, user_id=user.id, org_id=str(team.organization_id), team_id=team.id)
        cache.delete(pending_key)

        params = urlencode({"code": code, "state": _sanitize_state(state)})
        redirect_url = f"{callback_url}?{params}"

        capture_provisioning_event(
            "authorize_confirm", "success", partner=confirm_partner, team_id=team.id, **success_properties
        )

        return Response({"redirect_url": redirect_url})
