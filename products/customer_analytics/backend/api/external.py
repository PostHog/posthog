"""
External API endpoints for the Customer analytics product.

These endpoints are used by the CDP worker for workflow actions. Authenticated
via the team secret API token passed as a Bearer token in the Authorization header.
"""

import hashlib
from typing import Any

from django.db.models import Q

import structlog
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.models import Team

from products.customer_analytics.backend.models import Account

logger = structlog.get_logger(__name__)


class _ExternalAccountThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token (team secret_api_token)."""

    def get_cache_key(self, request: Request, view: APIView) -> str:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        ident = hashlib.sha256(token.encode()).hexdigest() if token else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ExternalAccountBurstThrottle(_ExternalAccountThrottle):
    scope = "external_account_burst"
    rate = "60/minute"


class ExternalAccountSustainedThrottle(_ExternalAccountThrottle):
    scope = "external_account_sustained"
    rate = "600/hour"


def _authenticate_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Extract Bearer token from Authorization header and validate against a team."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, Response({"error": "Missing or invalid Authorization header"}, status=status.HTTP_401_UNAUTHORIZED)

    api_key = auth_header[7:].strip()
    if not api_key:
        return None, Response({"error": "Empty API key"}, status=status.HTTP_401_UNAUTHORIZED)

    # Authenticate against secret_api_token (not api_token) because api_token
    # is the public project key embedded in client-side JS and visible to anyone.
    try:
        team = Team.objects.get(Q(secret_api_token=api_key) | Q(secret_api_token_backup=api_key))
    except (Team.DoesNotExist, Team.MultipleObjectsReturned):
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    return team, None


def _serialize_account(account: Account) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "external_id": account.external_id,
        "name": account.name,
        "properties": account.properties.model_dump(mode="json"),
    }


def _get_account_by_external_id(team: Team, external_id: str) -> Account | None:
    try:
        return Account.objects.for_team(team.id).get(external_id=external_id)
    except Account.DoesNotExist:
        return None


class ExternalAccountView(APIView):
    """
    GET /api/customer_analytics/external/account?external_id=<external_id> — Fetch account data

    Authenticated via Bearer token (team secret_api_token) in Authorization header.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ExternalAccountBurstThrottle, ExternalAccountSustainedThrottle]

    def get(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        external_id = request.query_params.get("external_id", "").strip()
        if not external_id:
            return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        account = _get_account_by_external_id(team, external_id)
        if account is None:
            return Response({"error": "Account not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(_serialize_account(account))
