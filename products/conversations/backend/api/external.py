"""
External API endpoints for the Conversations product.

These endpoints are used by the CDP worker for workflow actions and can be opened
to third-party developers in the future.
Authenticated via a project secret API key passed as a Bearer token in the
Authorization header.

This route is legacy (#82564 tracks the worker's move to the scoped-JWT internal
route, api/internal.py). Both routes share the handlers in api/ticket_actions.py.
"""

import hashlib
from typing import Any, cast

from django.http import HttpRequest

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.models import Team
from posthog.permissions import get_authenticator_scopes, is_authenticated_via_project_secret_api_key

from products.conversations.backend.api.ticket_actions import handle_ticket_get, wants_first_customer_message_text
from products.conversations.backend.metrics import TICKET_ACTION_AUTH_COUNTER


class _ExternalTicketThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token."""

    def get_cache_key(self, request, view):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        ident = hashlib.sha256(token.encode()).hexdigest() if token else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ExternalTicketBurstThrottle(_ExternalTicketThrottle):
    scope = "external_ticket_burst"
    rate = "120/minute"


class ExternalTicketSustainedThrottle(_ExternalTicketThrottle):
    scope = "external_ticket_sustained"
    rate = "1200/hour"


class ExternalTicketProjectSecretAPIKeyAuthentication(ProjectSecretAPIKeyAuthentication):
    """Returns None instead of raising when the key's team has conversations disabled, so
    such a key is indistinguishable from an unknown token."""

    activity_credential_type = "project_secret_key"

    def authenticate(self, request: HttpRequest | Request) -> tuple[Any, None] | None:
        result = super().authenticate(request)
        if result is None:
            return None
        team = self.project_secret_api_key.team
        # This AllowAny view never runs ActiveOrganizationPermission, so the organization
        # state must be enforced here or a key outlives its deactivated organization.
        organization = team.organization
        if not team.conversations_enabled or not organization.is_active or organization.is_pending_deletion:
            return None
        return result


def _authenticate_psak_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Resolve the team from a project secret API key with the ``support_ticket:read`` scope."""
    if not is_authenticated_via_project_secret_api_key(request):
        return None, Response({"error": "Missing or invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    authenticator = cast(ExternalTicketProjectSecretAPIKeyAuthentication, request.successful_authenticator)
    key_scopes = set(get_authenticator_scopes(authenticator) or [])
    if "*" not in key_scopes and "support_ticket:read" not in key_scopes:
        return None, Response(
            {"error": "API key missing required scope 'support_ticket:read'"},
            status=status.HTTP_403_FORBIDDEN,
        )

    return authenticator.project_secret_api_key.team, None


class ExternalTicketView(APIView):
    """
    GET /api/conversations/external/ticket/<ticket_id>  — Fetch ticket data

    Accepts a project secret API key with the ``support_ticket:read`` scope as a
    Bearer token. Ticket updates go through the scoped-JWT internal route.
    """

    authentication_classes = [ExternalTicketProjectSecretAPIKeyAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ExternalTicketBurstThrottle, ExternalTicketSustainedThrottle]

    def get(self, request: Request, ticket_id: str) -> Response:
        team, error = _authenticate_psak_team(request)
        if error:
            return error
        TICKET_ACTION_AUTH_COUNTER.labels(auth_method="project_secret_api_key", http_method="get").inc()

        assert team is not None

        return handle_ticket_get(
            team, ticket_id, include_first_customer_message_text=wants_first_customer_message_text(request)
        )
