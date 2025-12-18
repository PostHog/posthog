"""
Widget API endpoints for the Conversations product.

These endpoints are public (authenticated via public token) and used by the posthog-js widget.

Security model:
- `widget_session_id`: Random UUID generated client-side, stored in localStorage. Used for ACCESS CONTROL.
  (NOT the same as PostHog's session replay session_id - this one is persistent and never resets)
- `distinct_id`: PostHog's user identifier. Used for PERSON LINKING only, not access control.

This prevents users from accessing others' chats by knowing their email.
"""

import html
import uuid
import hashlib
import logging
from typing import Optional

from django.db.models import F, Q

from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.models import Team
from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket

logger = logging.getLogger(__name__)

# Widget-specific throttle classes


class WidgetUserBurstThrottle(SimpleRateThrottle):
    """Rate limit per widget_session_id or IP for POST/GET requests."""

    scope = "widget_user_burst"
    rate = "30/minute"

    def get_cache_key(self, request, view):
        # Throttle by widget_session_id if available, otherwise by IP
        widget_session_id = request.data.get("widget_session_id") or request.query_params.get("widget_session_id")
        if widget_session_id:
            ident = hashlib.sha256(widget_session_id.encode()).hexdigest()
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class WidgetTeamThrottle(SimpleRateThrottle):
    """Rate limit per team token."""

    scope = "widget_team"
    rate = "1000/hour"

    def get_cache_key(self, request, view):
        # Throttle by team token
        token = request.headers.get("X-Conversations-Token", "")
        ident = hashlib.sha256(token.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


class WidgetAuthentication(BaseAuthentication):
    """
    Authenticate widget requests via conversations_settings.widget_public_token.
    This provides team-level authentication only. User-level scoping
    is enforced via widget_session_id validation in each endpoint.
    """

    def authenticate(self, request: Request) -> tuple[None, Team]:
        """
        Returns (None, team) on success.
        No user object since this is public widget auth.
        """
        token = request.headers.get("X-Conversations-Token")
        if not token:
            raise AuthenticationFailed("X-Conversations-Token header required")

        try:
            team = Team.objects.get(conversations_settings__widget_public_token=token, conversations_enabled=True)
        except Team.DoesNotExist:
            raise AuthenticationFailed("Invalid token or conversations not enabled")

        return (None, team)


# Validation helpers


def validate_widget_session_id(widget_session_id: Optional[str]) -> str:
    """
    Validate widget_session_id is present and is a valid UUID.
    Widget session ID is used for access control - must be unguessable.
    Note: This is NOT the same as PostHog's session replay session_id.
    """
    if not widget_session_id:
        raise ValidationError("widget_session_id is required")

    if len(widget_session_id) > 64:
        raise ValidationError("widget_session_id too long (max 64 chars)")

    # Validate UUID format
    try:
        uuid.UUID(widget_session_id)
    except ValueError:
        raise ValidationError("widget_session_id must be a valid UUID")

    return widget_session_id


def validate_distinct_id(distinct_id: Optional[str]) -> str:
    """
    Validate distinct_id is present and within length limits.
    PostHog allows any distinct_id format.
    Note: distinct_id is used for Person linking only, not access control.
    """
    if not distinct_id:
        raise ValidationError("distinct_id is required")

    if len(distinct_id) > 200:
        raise ValidationError("distinct_id too long (max 200 chars)")

    return distinct_id


def sanitize_message_content(content: str) -> str:
    """
    Sanitize message content.
    For MVP: strip/escape all HTML.
    Post-MVP: could use allowlist with bleach library.
    """
    if not content:
        raise ValidationError("message content is required")

    if len(content) > 5000:
        raise ValidationError("Message too long (max 5000 chars)")

    # Escape HTML for safety
    return html.escape(content.strip())


def validate_traits(traits: dict) -> dict:
    """Validate customer traits dictionary."""
    if not isinstance(traits, dict):
        raise ValidationError("traits must be a dictionary")

    validated = {}
    for key, value in traits.items():
        # Only allow string values for MVP
        if not isinstance(value, str | int | float | bool | None):
            continue

        # Convert to string and validate length
        str_value = str(value) if value is not None else None
        if str_value and len(str_value) > 500:
            raise ValidationError(f"Trait value too long for {key} (max 500 chars)")

        validated[key] = str_value

    return validated


def validate_origin(request: Request, team: Team) -> bool:
    """
    Validate request origin to prevent token reuse on unauthorized domains.
    Checks against team.conversations_settings.widget_domains if configured.
    Empty list = allow all domains.
    """
    from posthog.api.utils import on_permitted_recording_domain

    settings = team.conversations_settings or {}
    domains = settings.get("widget_domains") or []

    if not domains:
        return True

    return on_permitted_recording_domain(domains, request._request)


# API Views
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

        team: Team = request.auth  # type: ignore[assignment]

        # Check honeypot field (bots fill this)
        if request.data.get("_hp"):
            return Response({"error": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate origin
        if not validate_origin(request, team):
            return Response({"error": "Origin not allowed"}, status=status.HTTP_403_FORBIDDEN)

        try:
            # Validate and extract data
            widget_session_id = validate_widget_session_id(request.data.get("widget_session_id"))
            distinct_id = validate_distinct_id(request.data.get("distinct_id"))
            message_content = sanitize_message_content(request.data.get("message", ""))
            traits = validate_traits(request.data.get("traits", {}))
            ticket_id = request.data.get("ticket_id")  # Optional: for adding to existing ticket

        except ValidationError:
            logger.exception("Validation error in WidgetMessageView")
            return Response({"error": "Invalid request data"}, status=status.HTTP_400_BAD_REQUEST)

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

                # Increment unread count for team (customer sent a message)
                ticket.unread_team_count = F("unread_team_count") + 1
                ticket.save(update_fields=["distinct_id", "anonymous_traits", "unread_team_count", "updated_at"])
                ticket.refresh_from_db()

            except Ticket.DoesNotExist:
                return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            # Find existing ticket by widget_session_id or create new one
            existing_ticket = Ticket.objects.filter(
                team=team, widget_session_id=widget_session_id, channel_source="widget"
            ).first()

            if existing_ticket:
                ticket = existing_ticket
                # Update distinct_id if changed (anonymous → identified)
                if ticket.distinct_id != distinct_id:
                    ticket.distinct_id = distinct_id
                if traits:
                    ticket.anonymous_traits.update(traits)
                # Increment unread count for team
                ticket.unread_team_count = F("unread_team_count") + 1
                ticket.save(update_fields=["distinct_id", "anonymous_traits", "unread_team_count", "updated_at"])
                ticket.refresh_from_db()
            else:
                # Create new ticket (first message is unread for team)
                ticket = Ticket.objects.create(
                    team=team,
                    widget_session_id=widget_session_id,
                    distinct_id=distinct_id,
                    channel_source="widget",
                    status="new",
                    anonymous_traits=traits,
                    unread_team_count=1,
                )

        # Create message
        comment = Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=message_content,
            item_context={"author_type": "customer", "distinct_id": distinct_id, "is_private": False},
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

        team: Team = request.auth  # type: ignore[assignment]

        try:
            widget_session_id = validate_widget_session_id(request.query_params.get("widget_session_id"))
        except ValidationError:
            logger.exception("Validation error in WidgetMessagesView")
            return Response({"error": "Invalid request data"}, status=status.HTTP_400_BAD_REQUEST)

        # Get ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id, team=team)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        # CRITICAL: Verify the ticket belongs to this widget_session_id (NOT distinct_id)
        if ticket.widget_session_id != widget_session_id:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Get query parameters
        after = request.query_params.get("after")  # ISO timestamp
        limit = min(int(request.query_params.get("limit", 100)), 500)  # Max 500

        # Build query
        messages_query = Comment.objects.filter(
            team=team, scope="conversations_ticket", item_id=str(ticket_id), deleted=False
        )

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

        return Response(
            {
                "ticket_id": str(ticket.id),
                "ticket_status": ticket.status,
                "unread_count": ticket.unread_customer_count,
                "messages": message_list,
                "has_more": len(messages) == limit,  # Hint if there are more messages
            }
        )


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

        team: Team = request.auth  # type: ignore[assignment]

        try:
            widget_session_id = validate_widget_session_id(request.query_params.get("widget_session_id"))
        except ValidationError:
            logger.exception("Validation error in WidgetTicketsView")
            return Response({"error": "Invalid request data"}, status=status.HTTP_400_BAD_REQUEST)

        # Query parameters
        status_filter = request.query_params.get("status")
        limit = min(int(request.query_params.get("limit", 10)), 50)  # Max 50
        offset = int(request.query_params.get("offset", 0))

        # Build query - filter by widget_session_id, not distinct_id
        tickets_query = Ticket.objects.filter(team=team, widget_session_id=widget_session_id)

        if status_filter:
            tickets_query = tickets_query.filter(status=status_filter)

        # Order and paginate
        tickets = tickets_query.order_by("-created_at")[offset : offset + limit]
        total_count = tickets_query.count()

        # Get message data for each ticket
        ticket_list = []
        for ticket in tickets:
            # Get message count and last message
            comments = Comment.objects.filter(
                team=team, scope="conversations_ticket", item_id=str(ticket.id), deleted=False
            ).order_by("-created_at")

            message_count = comments.count()
            last_comment = comments.first()

            ticket_list.append(
                {
                    "id": str(ticket.id),
                    "status": ticket.status,
                    "unread_count": ticket.unread_customer_count,  # Unread messages for customer
                    "last_message": last_comment.content if last_comment else None,
                    "last_message_at": last_comment.created_at.isoformat() if last_comment else None,
                    "message_count": message_count,
                    "created_at": ticket.created_at.isoformat(),
                }
            )

        return Response({"count": total_count, "results": ticket_list})


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

        team: Team = request.auth  # type: ignore[assignment]

        try:
            widget_session_id = validate_widget_session_id(request.data.get("widget_session_id"))
        except ValidationError:
            logger.exception("Validation error in WidgetMarkReadView")
            return Response({"error": "Invalid request data"}, status=status.HTTP_400_BAD_REQUEST)

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
