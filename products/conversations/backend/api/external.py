"""
External API endpoints for the Conversations product.

These endpoints are used by the CDP worker for workflow actions and can be opened
to third-party developers in the future.
Authenticated via team secret API token passed as a Bearer token in the Authorization header.

This auth path is legacy (#82564 tracks the worker's move to the scoped-JWT internal
route, api/internal.py). Both routes share the handlers in api/ticket_actions.py.
"""

import hashlib

from django.db.models import Q

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.models import Team

from products.conversations.backend.api.ticket_actions import handle_ticket_get, handle_ticket_patch
from products.conversations.backend.metrics import TICKET_ACTION_AUTH_COUNTER


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
    return team, None


class ExternalTicketView(APIView):
    """
    GET /api/conversations/external/ticket/<ticket_id>  — Fetch ticket data
    PATCH /api/conversations/external/ticket/<ticket_id> — Update ticket fields

    Authenticated via Bearer token (team secret_api_token) in Authorization header.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ExternalTicketBurstThrottle, ExternalTicketSustainedThrottle]

    def get(self, request: Request, ticket_id: str) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        return handle_ticket_get(team, ticket_id)

    def patch(self, request: Request, ticket_id: str) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        return handle_ticket_patch(request, team, ticket_id)
