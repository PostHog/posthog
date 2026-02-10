"""
External API endpoints for the Conversations product.

These endpoints are used by the CDP worker for workflow actions and can be opened
to third-party developers in the future.
Authenticated via team API token passed as a Bearer token in the Authorization header.
"""

import hashlib

from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.models import Team

from products.conversations.backend.cache import invalidate_unread_count_cache
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Priority, Status


class _ExternalTicketThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token (team api_token)."""

    def get_cache_key(self, request, view):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        ident = hashlib.sha256(token.encode()).hexdigest() if token else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ExternalTicketBurstThrottle(_ExternalTicketThrottle):
    scope = "external_ticket_burst"
    rate = "60/minute"


class ExternalTicketSustainedThrottle(_ExternalTicketThrottle):
    scope = "external_ticket_sustained"
    rate = "600/hour"


def _authenticate_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Extract Bearer token from Authorization header and validate against team."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, Response({"error": "Missing or invalid Authorization header"}, status=status.HTTP_401_UNAUTHORIZED)

    api_key = auth_header[7:].strip()
    if not api_key:
        return None, Response({"error": "Empty API key"}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        team = Team.objects.get(api_token=api_key)
    except Team.DoesNotExist:
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    return team, None


class ExternalTicketUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[s.value for s in Status], required=False)
    priority = serializers.ChoiceField(choices=[p.value for p in Priority], required=False)


class ExternalTicketView(APIView):
    """
    GET /api/conversations/external/ticket/<ticket_id>  — Fetch ticket data
    PATCH /api/conversations/external/ticket/<ticket_id> — Update ticket fields

    Authenticated via Bearer token (team api_token) in Authorization header.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ExternalTicketBurstThrottle, ExternalTicketSustainedThrottle]

    def get(self, request: Request, ticket_id: str) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        try:
            ticket = Ticket.objects.get(id=ticket_id, team_id=team.id)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "priority": ticket.priority,
                "channel_source": ticket.channel_source,
                "distinct_id": ticket.distinct_id,
                "created_at": ticket.created_at.isoformat(),
                "updated_at": ticket.updated_at.isoformat(),
                "message_count": ticket.message_count,
                "last_message_at": ticket.last_message_at.isoformat() if ticket.last_message_at else None,
                "last_message_text": ticket.last_message_text,
                "unread_team_count": ticket.unread_team_count,
                "unread_customer_count": ticket.unread_customer_count,
            }
        )

    def patch(self, request: Request, ticket_id: str) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        serializer = ExternalTicketUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ticket = Ticket.objects.get(id=ticket_id, team_id=team.id)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        update_fields: list[str] = []

        new_status = serializer.validated_data.get("status")
        if new_status is not None:
            old_status = ticket.status
            ticket.status = new_status
            update_fields.append("status")

            if old_status == "resolved" or new_status == "resolved":
                invalidate_unread_count_cache(team.id)

        new_priority = serializer.validated_data.get("priority")
        if new_priority is not None:
            ticket.priority = new_priority
            update_fields.append("priority")

        if update_fields:
            ticket.save(update_fields=[*update_fields, "updated_at"])

        return Response({"ok": True})
