"""
External API endpoints for the Conversations product.

These endpoints are used by the CDP worker for workflow actions and can be opened
to third-party developers in the future.
Authenticated via team secret API token passed as a Bearer token in the Authorization header.

This auth path is legacy (#82564 tracks the worker's move to the scoped-JWT internal
route, api/internal.py). Both routes share the handlers in api/ticket_actions.py.
"""

import hashlib
from typing import Any, cast

from django.db.models import Q
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

from products.conversations.backend.api.ticket_actions import (
    handle_ticket_get,
    handle_ticket_patch,
    wants_first_customer_message_text,
)
from products.conversations.backend.metrics import LEGACY_TICKET_AUTH_BY_TEAM_COUNTER, TICKET_ACTION_AUTH_COUNTER


class _ExternalTicketThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token (team secret_api_token)."""

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
    # A migrated legacy token (#63111) must keep the legacy path: PATCH accepts it there
    # but refuses PSAKs, and the legacy-usage counters would otherwise go silent.
    defer_migrated_team_tokens = True

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


def _authenticate_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Extract Bearer token from Authorization header and validate against team."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, Response({"error": "Missing or invalid Authorization header"}, status=status.HTTP_401_UNAUTHORIZED)

    api_key = auth_header[7:].strip()
    if not api_key:
        return None, Response({"error": "Empty API key"}, status=status.HTTP_401_UNAUTHORIZED)

    # Authenticate against secret_api_token (not api_token) because api_token
    # is the public project key embedded in client-side JS and visible to anyone.
    try:
        team = Team.objects.get(
            Q(secret_api_token=api_key) | Q(secret_api_token_backup=api_key),
            conversations_enabled=True,
        )
    except (Team.DoesNotExist, Team.MultipleObjectsReturned):
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    TICKET_ACTION_AUTH_COUNTER.labels(auth_method="secret_api_token", http_method=(request.method or "").lower()).inc()
    LEGACY_TICKET_AUTH_BY_TEAM_COUNTER.labels(team_id=str(team.id)).inc()
    return team, None


class ExternalTicketView(APIView):
    """
    GET /api/conversations/external/ticket/<ticket_id>  — Fetch ticket data
    PATCH /api/conversations/external/ticket/<ticket_id> — Update ticket fields

    GET accepts the team secret_api_token or a project secret API key with the
    ``support_ticket:read`` scope as a Bearer token. PATCH accepts only the team
    secret_api_token.
    """

    authentication_classes = [ExternalTicketProjectSecretAPIKeyAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ExternalTicketBurstThrottle, ExternalTicketSustainedThrottle]

    def get(self, request: Request, ticket_id: str) -> Response:
        if is_authenticated_via_project_secret_api_key(request):
            team, error = _authenticate_psak_team(request)
            if not error:
                TICKET_ACTION_AUTH_COUNTER.labels(auth_method="project_secret_api_key", http_method="get").inc()
        else:
            team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        return handle_ticket_get(
            team, ticket_id, include_first_customer_message_text=wants_first_customer_message_text(request)
        )

    def patch(self, request: Request, ticket_id: str) -> Response:
        if is_authenticated_via_project_secret_api_key(request):
            return Response(
                {"error": "Project secret API keys can only read tickets on this route"},
                status=status.HTTP_403_FORBIDDEN,
            )
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        return handle_ticket_patch(request, team, ticket_id)
