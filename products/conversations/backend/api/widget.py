"""
Widget API endpoints for the Conversations product.

These endpoints are public (authenticated via public token) and used by the posthog-js widget.

Security model:
- `widget_session_id`: Random UUID generated client-side, stored in localStorage. Used for ACCESS CONTROL.
- `distinct_id`: PostHog's user identifier. Used for PERSON LINKING only, not access control.

This prevents users from accessing others' chats by knowing their email.
"""

import logging

from django.db.models import F, Q

from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import WidgetAuthentication
from posthog.models import Team
from posthog.models.comment import Comment
from posthog.rate_limit import WidgetTeamThrottle, WidgetUserBurstThrottle
from posthog.tasks.email import send_new_ticket_notification

from products.conversations.backend.api.serializers import (
    WidgetMarkReadSerializer,
    WidgetMessageSerializer,
    WidgetMessagesQuerySerializer,
    WidgetTicketsQuerySerializer,
    validate_origin,
)
from products.conversations.backend.cache import (
    get_cached_messages,
    get_cached_tickets,
    invalidate_unread_count_cache,
    set_cached_messages,
    set_cached_tickets,
)
from products.conversations.backend.models import Ticket

logger = logging.getLogger(__name__)


class WidgetMessageView(APIView):
    """
    POST /api/conversations/v1/widget/message
    Create a new message in a ticket (or create ticket if first message).

    Security: Access controlled by widget_session_id (random UUID), not distinct_id.
    """

    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [WidgetUserBurstThrottle, WidgetTeamThrottle]

    def post(self, request: Request) -> Response:
        """Handle incoming message from widget."""

        team: Team | None = request.auth  # type: ignore[assignment]
        if not team:
            return Response({"error": "Authentication required"}, status=status.HTTP_403_FORBIDDEN)

        # Check honeypot field (bots fill this)
        if request.data.get("_hp"):
            return Response({"error": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate origin
        if not validate_origin(request, team):
            return Response({"error": "Origin not allowed"}, status=status.HTTP_403_FORBIDDEN)

        # Validate and extract data
        serializer = WidgetMessageSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Validation error in WidgetMessageView", extra={"errors": serializer.errors})
            return Response(
                {"error": "Invalid request data", "details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST
            )

        widget_session_id = str(serializer.validated_data["widget_session_id"])
        distinct_id = serializer.validated_data["distinct_id"]
        message_content = serializer.validated_data["message"]
        traits = serializer.validated_data.get("traits", {})
        session_id = serializer.validated_data.get("session_id")
        session_context = serializer.validated_data.get("session_context", {})

        # Handle optional ticket_id (UUID field)
        raw_ticket_id = request.data.get("ticket_id")
        ticket_id = None
        if raw_ticket_id:
            try:
                ticket_id = str(serializers.UUIDField().to_internal_value(raw_ticket_id))
            except ValidationError:
                return Response({"error": "Invalid ticket_id format"}, status=status.HTTP_400_BAD_REQUEST)

        # Find or create ticket
        if ticket_id:
            # Adding to existing ticket
            try:
                ticket = Ticket.objects.get(id=ticket_id, team=team)

                # CRITICAL: Verify ticket belongs to this widget_session_id (NOT distinct_id)
                if ticket.widget_session_id != widget_session_id:
                    return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

                # Update distinct_id if changed (anonymous → identified transition)
                if ticket.distinct_id != distinct_id:
                    ticket.distinct_id = distinct_id

                # Update traits if provided
                if traits:
                    ticket.anonymous_traits.update(traits)

                # Update session data if provided
                if session_id:
                    ticket.session_id = session_id
                if session_context:
                    ticket.session_context.update(session_context)

                # Increment unread count for team (customer sent a message)
                ticket.unread_team_count = F("unread_team_count") + 1
                ticket.save(
                    update_fields=[
                        "distinct_id",
                        "anonymous_traits",
                        "session_id",
                        "session_context",
                        "unread_team_count",
                        "updated_at",
                    ]
                )
                ticket.refresh_from_db()
                # Invalidate unread count cache - customer message increases count
                invalidate_unread_count_cache(team.id)

            except Ticket.DoesNotExist:
                return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            # No ticket_id provided - always create a new ticket
            ticket = Ticket.objects.create_with_number(
                team=team,
                widget_session_id=widget_session_id,
                distinct_id=distinct_id,
                channel_source="widget",
                status="new",
                anonymous_traits=traits,
                unread_team_count=1,
                session_id=session_id,
                session_context=session_context,
            )
            # Invalidate unread count cache - new ticket with unread message
            invalidate_unread_count_cache(team.id)

        # Create message
        comment = Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=message_content,
            item_context={"author_type": "customer", "distinct_id": distinct_id, "is_private": False},
        )

        # Send email notification for new tickets
        if not ticket_id:
            conversations_settings = team.conversations_settings or {}
            if conversations_settings.get("notification_recipients"):
                send_new_ticket_notification.delay(
                    ticket_id=str(ticket.id),
                    team_id=team.id,
                    first_message_content=message_content,
                )

        return Response(
            {
                "ticket_id": str(ticket.id),
                "message_id": str(comment.id),
                "ticket_status": ticket.status,
                "unread_count": ticket.unread_customer_count,  # Unread messages for customer
                "created_at": comment.created_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class WidgetMessagesView(APIView):
    """
    GET /api/conversations/v1/widget/messages/<ticket_id>
    Fetch messages for a specific ticket.

    Security: Access controlled by widget_session_id (random UUID), not distinct_id.
    """

    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [WidgetUserBurstThrottle, WidgetTeamThrottle]

    def get(self, request: Request, ticket_id: str) -> Response:
        """Get messages for a ticket."""

        team: Team | None = request.auth  # type: ignore[assignment]
        if not team:
            return Response({"error": "Authentication required"}, status=status.HTTP_403_FORBIDDEN)

        # Validate ticket_id (URL parameter)
        try:
            ticket_id = str(serializers.UUIDField().to_internal_value(ticket_id))
        except ValidationError:
            return Response({"error": "Invalid ticket_id format"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate query parameters
        query_serializer = WidgetMessagesQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {"error": "Invalid request data", "details": query_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        widget_session_id = str(query_serializer.validated_data["widget_session_id"])
        after = query_serializer.validated_data.get("after")
        limit = query_serializer.validated_data["limit"]

        # Get ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id, team=team)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        # CRITICAL: Verify the ticket belongs to this widget_session_id (NOT distinct_id)
        if ticket.widget_session_id != widget_session_id:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Check cache (after stays constant between polls until new message arrives)
        after_str = after.isoformat() if after else None
        use_cache = limit == 50  # Only cache the limit used by widget polling
        if use_cache:
            cached = get_cached_messages(team.id, ticket_id, after_str)
            if cached is not None:
                return Response(cached)

        # Build query - prefetch created_by to avoid N+1 queries
        messages_query = Comment.objects.filter(
            team=team, scope="conversations_ticket", item_id=str(ticket_id), deleted=False
        ).select_related("created_by")

        # Filter by timestamp if provided
        if after:
            messages_query = messages_query.filter(created_at__gt=after)

        # Only return non-private messages to widget
        messages_query = messages_query.filter(Q(item_context__is_private=False) | Q(item_context__is_private=None))

        # Order and limit
        messages = messages_query.order_by("created_at")[:limit]

        # Serialize messages
        message_list = []
        for m in messages:
            author_type = m.item_context.get("author_type", "customer") if m.item_context else "customer"

            # Get author name
            if m.created_by:
                author_name = m.created_by.first_name or m.created_by.email
            elif author_type == "customer":
                author_name = ticket.anonymous_traits.get("name") or ticket.anonymous_traits.get("email") or "You"
            elif author_type == "AI":
                author_name = "PostHog Assistant"
            else:
                author_name = "Support"

            message_list.append(
                {
                    "id": str(m.id),
                    "content": m.content,
                    "author_type": author_type,
                    "author_name": author_name,
                    "created_at": m.created_at.isoformat(),
                    "is_private": m.item_context.get("is_private", False) if m.item_context else False,
                }
            )

        response_data = {
            "ticket_id": str(ticket.id),
            "ticket_status": ticket.status,
            "unread_count": ticket.unread_customer_count,
            "messages": message_list,
            "has_more": len(messages) == limit,  # Hint if there are more messages
        }

        # Cache the response
        if use_cache:
            set_cached_messages(team.id, ticket_id, response_data, after_str)

        return Response(response_data)


class WidgetTicketsView(APIView):
    """
    GET /api/conversations/v1/widget/tickets
    List all tickets for current widget_session_id (for conversation history).

    Security: Lists tickets by widget_session_id, not distinct_id.
    Users only see tickets from their browser session.
    """

    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [WidgetUserBurstThrottle, WidgetTeamThrottle]

    def get(self, request: Request) -> Response:
        """List tickets for a widget_session_id."""

        team: Team | None = request.auth  # type: ignore[assignment]
        if not team:
            return Response({"error": "Authentication required"}, status=status.HTTP_403_FORBIDDEN)

        # Validate query parameters
        query_serializer = WidgetTicketsQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {"error": "Invalid request data", "details": query_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        widget_session_id = str(query_serializer.validated_data["widget_session_id"])
        status_filter = query_serializer.validated_data.get("status")
        limit = query_serializer.validated_data["limit"]
        offset = query_serializer.validated_data["offset"]

        # Check cache for first page (most common case for polling)
        if offset == 0:
            cached = get_cached_tickets(team.id, widget_session_id, status_filter)
            if cached is not None:
                return Response(cached)

        # Build query - filter by widget_session_id, not distinct_id
        tickets_query = Ticket.objects.filter(team=team, widget_session_id=widget_session_id)

        if status_filter:
            tickets_query = tickets_query.filter(status=status_filter)

        # message_count, last_message_at, last_message_text are now denormalized on Ticket model

        # Order and paginate
        tickets = tickets_query.order_by("-created_at")[offset : offset + limit]
        total_count = tickets_query.count()

        # Serialize tickets
        ticket_list = []
        for ticket in tickets:
            ticket_list.append(
                {
                    "id": str(ticket.id),
                    "status": ticket.status,
                    "unread_count": ticket.unread_customer_count,  # Unread messages for customer
                    "last_message": ticket.last_message_text,  # Now from denormalized field
                    "last_message_at": ticket.last_message_at.isoformat() if ticket.last_message_at else None,
                    "message_count": ticket.message_count,
                    "created_at": ticket.created_at.isoformat(),
                }
            )

        response_data = {"count": total_count, "results": ticket_list}

        # Cache first page
        if offset == 0:
            set_cached_tickets(team.id, widget_session_id, response_data, status_filter)

        return Response(response_data)


class WidgetMarkReadView(APIView):
    """
    POST /api/conversations/v1/widget/messages/<ticket_id>/read
    Mark all messages in a ticket as read by the customer.

    This resets unread_customer_count to 0.
    """

    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [WidgetUserBurstThrottle, WidgetTeamThrottle]

    def post(self, request: Request, ticket_id: str) -> Response:
        """Mark ticket messages as read by customer."""

        team: Team | None = request.auth  # type: ignore[assignment]
        if not team:
            return Response({"error": "Authentication required"}, status=status.HTTP_403_FORBIDDEN)

        # Validate ticket_id (URL parameter)
        try:
            ticket_id = str(serializers.UUIDField().to_internal_value(ticket_id))
        except ValidationError:
            return Response({"error": "Invalid ticket_id format"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate request body
        body_serializer = WidgetMarkReadSerializer(data=request.data)
        if not body_serializer.is_valid():
            return Response(
                {"error": "Invalid request data", "details": body_serializer.errors}, status=status.HTTP_400_BAD_REQUEST
            )

        widget_session_id = str(body_serializer.validated_data["widget_session_id"])

        # Get ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id, team=team)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        # CRITICAL: Verify the ticket belongs to this widget_session_id
        if ticket.widget_session_id != widget_session_id:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Reset unread count for customer
        if ticket.unread_customer_count > 0:
            ticket.unread_customer_count = 0
            ticket.save(update_fields=["unread_customer_count", "updated_at"])

        return Response({"success": True, "unread_count": 0})
