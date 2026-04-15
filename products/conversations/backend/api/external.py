"""
External API endpoints for the Conversations product.

These endpoints are used by the CDP worker for workflow actions and can be opened
to third-party developers in the future.
Authenticated via team secret API token passed as a Bearer token in the Authorization header.
"""

import hashlib

from django.db.models import Q

import structlog
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.exceptions_capture import capture_exception
from posthog.models import Tag, Team
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.tag import tagify

from products.conversations.backend.api.tickets import assign_ticket
from products.conversations.backend.cache import invalidate_unread_count_cache
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Priority, Status

logger = structlog.get_logger(__name__)


class _ExternalTicketThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token (team secret_api_token)."""

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

    # Authenticate against secret_api_token (not api_token) because api_token
    # is the public project key embedded in client-side JS and visible to anyone.
    try:
        team = Team.objects.get(
            Q(secret_api_token=api_key) | Q(secret_api_token_backup=api_key),
            conversations_enabled=True,
        )
    except (Team.DoesNotExist, Team.MultipleObjectsReturned):
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    return team, None


class ExternalTicketUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[s.value for s in Status], required=False)
    priority = serializers.ChoiceField(choices=[p.value for p in Priority], required=False)
    sla_due_at = serializers.DateTimeField(required=False, allow_null=True)
    snoozed_until = serializers.DateTimeField(required=False, allow_null=True)
    assignee = serializers.JSONField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False)


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

        try:
            ticket = Ticket.objects.select_related("assignment", "assignment__user", "assignment__role").get(
                id=ticket_id, team_id=team.id
            )
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        assignee = None
        assignment = getattr(ticket, "assignment", None)
        if assignment:
            assignee = {
                "id": assignment.user_id
                if assignment.user_id
                else str(assignment.role_id)
                if assignment.role_id
                else None,
                "type": "role" if assignment.role_id else "user",
                "user": {"email": assignment.user.email} if assignment.user_id and assignment.user else None,
                "role": {"name": assignment.role.name} if assignment.role_id and assignment.role else None,
            }

        session_context = ticket.session_context or {}
        tags = list(ticket.tagged_items.values_list("tag__name", flat=True))

        return Response(
            {
                "id": str(ticket.id),
                "number": ticket.ticket_number,
                "status": ticket.status,
                "priority": ticket.priority,
                "channel_source": ticket.channel_source,
                "channel_detail": ticket.channel_detail,
                "distinct_id": ticket.distinct_id,
                "created_at": ticket.created_at.isoformat(),
                "updated_at": ticket.updated_at.isoformat(),
                "message_count": ticket.message_count,
                "last_message_at": ticket.last_message_at.isoformat() if ticket.last_message_at else None,
                "last_message_text": ticket.last_message_text,
                "unread_team_count": ticket.unread_team_count,
                "unread_customer_count": ticket.unread_customer_count,
                "sla": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
                "snoozed_until": ticket.snoozed_until.isoformat() if ticket.snoozed_until else None,
                "assignee": assignee,
                "url": session_context.get("current_url"),
                "slack_channel_id": ticket.slack_channel_id,
                "slack_thread_ts": ticket.slack_thread_ts,
                "slack_team_id": ticket.slack_team_id,
                "tags": tags,
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
        changes: list[Change] = []

        new_status = serializer.validated_data.get("status")
        old_status = ticket.status
        if new_status is not None:
            ticket.status = new_status
            update_fields.append("status")

            if old_status == "resolved" or new_status == "resolved":
                invalidate_unread_count_cache(team.id)

            if old_status != new_status:
                changes.append(
                    Change(
                        type="Ticket",
                        field="status",
                        before=old_status,
                        after=new_status,
                        action="changed",
                    )
                )

        new_priority = serializer.validated_data.get("priority")
        old_priority = ticket.priority
        if new_priority is not None:
            ticket.priority = new_priority
            update_fields.append("priority")

            if old_priority != new_priority:
                changes.append(
                    Change(
                        type="Ticket",
                        field="priority",
                        before=old_priority,
                        after=new_priority,
                        action="changed",
                    )
                )

        old_sla_due_at = ticket.sla_due_at
        if "sla_due_at" in serializer.validated_data:
            ticket.sla_due_at = serializer.validated_data["sla_due_at"]
            update_fields.append("sla_due_at")

            if old_sla_due_at != ticket.sla_due_at:
                changes.append(
                    Change(
                        type="Ticket",
                        field="sla_due_at",
                        before=old_sla_due_at.isoformat() if old_sla_due_at else None,
                        after=ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
                        action="changed",
                    )
                )

        old_snoozed_until = ticket.snoozed_until
        if "snoozed_until" in serializer.validated_data:
            ticket.snoozed_until = serializer.validated_data["snoozed_until"]
            update_fields.append("snoozed_until")

            if old_snoozed_until != ticket.snoozed_until:
                changes.append(
                    Change(
                        type="Ticket",
                        field="snoozed_until",
                        before=old_snoozed_until.isoformat() if old_snoozed_until else None,
                        after=ticket.snoozed_until.isoformat() if ticket.snoozed_until else None,
                        action="changed",
                    )
                )

                # Auto-status on snooze transitions (only when status wasn't explicitly set)
                if new_status is None:
                    auto_status = None
                    if old_snoozed_until is None and ticket.snoozed_until is not None:
                        auto_status = "on_hold"
                    elif old_snoozed_until is not None and ticket.snoozed_until is None:
                        auto_status = "open"

                    if auto_status and ticket.status != auto_status:
                        auto_old_status = ticket.status
                        ticket.status = auto_status
                        if "status" not in update_fields:
                            update_fields.append("status")
                        changes.append(
                            Change(
                                type="Ticket",
                                field="status",
                                before=auto_old_status,
                                after=auto_status,
                                action="changed",
                            )
                        )

        if update_fields:
            ticket.save(update_fields=[*update_fields, "updated_at"])

        if changes:
            try:
                log_activity(
                    organization_id=team.organization_id,
                    team_id=team.id,
                    user=None,
                    was_impersonated=False,
                    item_id=str(ticket.id),
                    scope="Ticket",
                    activity="updated",
                    detail=Detail(
                        name=f"Ticket #{ticket.ticket_number}",
                        changes=changes,
                    ),
                )
            except Exception as e:
                capture_exception(e, {"ticket_id": str(ticket.id)})

        if "assignee" in serializer.validated_data:
            try:
                assign_ticket(
                    ticket=ticket,
                    assignee=serializer.validated_data.get("assignee"),
                    organization=team.organization,
                    user=None,
                    team_id=team.id,
                    was_impersonated=False,
                )
            except Exception as e:
                capture_exception(e, {"ticket_id": str(ticket.id)})
                return Response({"error": "Failed to assign ticket"}, status=status.HTTP_400_BAD_REQUEST)

        if "tags" in serializer.validated_data:
            try:
                new_tags = list({tagify(t) for t in serializer.validated_data["tags"]})
                for tag_name in new_tags:
                    tag_instance, _ = Tag.objects.get_or_create(name=tag_name, team_id=team.id)
                    ticket.tagged_items.get_or_create(tag_id=tag_instance.id)
                for tagged_item in ticket.tagged_items.exclude(tag__name__in=new_tags):
                    tagged_item.delete()
                Tag.objects.filter(team_id=team.id, tagged_items__isnull=True).delete()
            except Exception as e:
                capture_exception(e, {"ticket_id": str(ticket.id)})
                return Response({"error": "Failed to update tags"}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"ok": True})
