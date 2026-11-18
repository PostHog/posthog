"""
Internal account endpoints for the Customer analytics product.

The service-to-service surface the CDP worker's account workflow actions call. Callers
authenticate with a short-lived scoped service JWT pinned to one team and one account
external_id (#82564 tracks retiring the legacy secret_api_token routes in external.py).
Mounted under /api/projects/<team_id>/internal/ in posthog/urls.py, a namespace Contour
ingress does not expose, so the routes are unreachable from the public internet.
"""

from typing import Any, cast

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.models import Team
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.customer_analytics.backend.presentation.views.account_actions import (
    ACCOUNT_ACTION_AUTH_COUNTER,
    handle_account_create,
    handle_account_get,
    handle_account_set_properties,
    handle_account_update,
)
from products.customer_analytics.backend.presentation.views.external import _customer_analytics_enabled

CUSTOMER_ANALYTICS_ACCOUNTS_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.CUSTOMER_ANALYTICS_ACCOUNTS,
    settings_name="CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRETS",
)


class CustomerAnalyticsAccountJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = CUSTOMER_ANALYTICS_ACCOUNTS_PURPOSE


class InternalAccountView(APIView):
    """
    GET /api/projects/<team_id>/internal/customer_analytics/account?external_id=<id> — Fetch account data
    POST /api/projects/<team_id>/internal/customer_analytics/account — Create an account (no-op if it exists)
    PATCH /api/projects/<team_id>/internal/customer_analytics/account — Update relationships, tags, churn state

    JWT-only from birth: there is no legacy-token fallback here, so these routes never
    accept secret_api_token. The auth class binds the request to the token's team and
    rejects tokens whose team differs from the URL's.
    """

    authentication_classes = [CustomerAnalyticsAccountJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, team_id: str) -> Response:
        external_id = request.query_params.get("external_id", "").strip()
        team, error = _check_account_access(request, external_id)
        if error:
            return error
        assert team is not None
        ACCOUNT_ACTION_AUTH_COUNTER.labels(auth_method="scoped_jwt", http_method="get").inc()
        return handle_account_get(team, external_id)

    def post(self, request: Request, team_id: str) -> Response:
        team, error = _check_account_access(request, _external_id_from_body(request))
        if error:
            return error
        assert team is not None
        ACCOUNT_ACTION_AUTH_COUNTER.labels(auth_method="scoped_jwt", http_method="post").inc()
        return handle_account_create(request, team)

    def patch(self, request: Request, team_id: str) -> Response:
        team, error = _check_account_access(request, _external_id_from_body(request))
        if error:
            return error
        assert team is not None
        ACCOUNT_ACTION_AUTH_COUNTER.labels(auth_method="scoped_jwt", http_method="patch").inc()
        return handle_account_update(request, team)


class InternalAccountCustomPropertiesView(APIView):
    """
    PATCH /api/projects/<team_id>/internal/customer_analytics/account/custom_property_values — Set an
    account's custom property values. Same auth model as InternalAccountView.
    """

    authentication_classes = [CustomerAnalyticsAccountJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, team_id: str) -> Response:
        team, error = _check_account_access(request, _external_id_from_body(request))
        if error:
            return error
        assert team is not None
        ACCOUNT_ACTION_AUTH_COUNTER.labels(auth_method="scoped_jwt", http_method="patch").inc()
        return handle_account_set_properties(request, team)


def _external_id_from_body(request: Request) -> str:
    external_id = request.data.get("external_id") if isinstance(request.data, dict) else None
    return external_id.strip() if isinstance(external_id, str) else ""


def _check_account_access(request: Request, external_id: str) -> tuple[Team, None] | tuple[None, Response]:
    """Enforce the per-entity claim and the product gate after JWT authentication.

    The worker mints each token for one specific account external_id (create pins the id
    being created), so a token replayed with a different external_id is refused even within
    its own team. Missing claim or empty request id fails closed.
    """
    claims = cast(dict[str, Any], request.auth or {})
    # No str() on the claim: a missing claim would stringify to "None" and match an account
    # literally named "None" — only a real string passes, keeping an absent claim failing
    # closed. Stripped to mirror the request-side normalization, so a padded id behaves the
    # same here as on the legacy route.
    claim_external_id = claims.get("external_id")
    if not isinstance(claim_external_id, str):
        claim_external_id = None
    if not external_id or claim_external_id is None or claim_external_id.strip() != external_id:
        return None, Response(
            {"error": "Service token does not grant access to this account"}, status=status.HTTP_403_FORBIDDEN
        )

    # The auth class already verified the team claim exists, matches the URL, and names a real
    # team; fetch the full row because the handlers need organization access for assignments.
    # The team can still vanish between the two reads, so a clean 404 beats an unhandled 500.
    try:
        team = Team.objects.get(id=claims["team_id"])
    except Team.DoesNotExist:
        return None, Response({"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND)
    if not _customer_analytics_enabled(team):
        return None, Response(
            {"error": "Customer analytics is not enabled for this team"}, status=status.HTTP_403_FORBIDDEN
        )

    return team, None
