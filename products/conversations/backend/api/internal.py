"""
Internal ticket endpoints for the Conversations product.

The service-to-service surface the CDP worker's ticket workflow actions call. Callers
authenticate with a short-lived scoped service JWT pinned to one team and one ticket
(#82564 tracks retiring the legacy secret_api_token route in api/external.py). Mounted
under /api/projects/<team_id>/internal/ in posthog/urls.py, a namespace Contour ingress
does not expose, so the route is unreachable from the public internet.
"""

import uuid
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

from products.conversations.backend.api.ticket_actions import handle_ticket_get, handle_ticket_patch
from products.conversations.backend.metrics import TICKET_ACTION_AUTH_COUNTER

CONVERSATIONS_TICKETS_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.CONVERSATIONS_TICKETS,
    settings_name="CONVERSATIONS_TICKETS_JWT_SECRETS",
)


class ConversationsTicketJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = CONVERSATIONS_TICKETS_PURPOSE


class InternalTicketView(APIView):
    """
    GET /api/projects/<team_id>/internal/conversations/tickets/<ticket_id> — Fetch ticket data
    PATCH /api/projects/<team_id>/internal/conversations/tickets/<ticket_id> — Update ticket fields

    JWT-only from birth: there is no legacy-token fallback here, so this route never
    accepts secret_api_token. The auth class binds the request to the token's team and
    rejects tokens whose team differs from the URL's.
    """

    authentication_classes = [ConversationsTicketJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, team_id: str, ticket_id: uuid.UUID) -> Response:
        team, error = _check_ticket_access(request, ticket_id)
        if error:
            return error
        assert team is not None
        TICKET_ACTION_AUTH_COUNTER.labels(auth_method="scoped_jwt", http_method="get").inc()
        return handle_ticket_get(team, ticket_id)

    def patch(self, request: Request, team_id: str, ticket_id: uuid.UUID) -> Response:
        team, error = _check_ticket_access(request, ticket_id)
        if error:
            return error
        assert team is not None
        TICKET_ACTION_AUTH_COUNTER.labels(auth_method="scoped_jwt", http_method="patch").inc()
        return handle_ticket_patch(request, team, ticket_id)


def _check_ticket_access(request: Request, ticket_id: uuid.UUID) -> tuple[Team, None] | tuple[None, Response]:
    """Enforce the per-entity claim and the product gate after JWT authentication.

    The worker mints each token for one specific ticket, so a token replayed against a
    different ticket URL is refused even within its own team. Missing claim fails closed.
    """
    claims = cast(dict[str, Any], request.auth or {})
    if str(claims.get("ticket_id")) != str(ticket_id):
        return None, Response(
            {"error": "Service token does not grant access to this ticket"}, status=status.HTTP_403_FORBIDDEN
        )

    # The auth class already verified the team claim exists, matches the URL, and names a real
    # team; fetch the full row because the handlers need organization access for activity
    # logging and assignment. The team can still vanish between the two reads, so a clean 404
    # beats an unhandled 500.
    try:
        team = Team.objects.get(id=claims["team_id"])
    except Team.DoesNotExist:
        return None, Response({"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND)
    if not team.conversations_enabled:
        return None, Response({"error": "Conversations is not enabled for this team"}, status=status.HTTP_403_FORBIDDEN)

    return team, None
