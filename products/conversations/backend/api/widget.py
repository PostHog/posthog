"""
Widget API endpoints for the Conversations product.

These endpoints are public (authenticated via public token) and used by the posthog-js widget.

Security model:
- `widget_session_id`: Random UUID generated client-side, stored in localStorage. Used for ACCESS CONTROL.
- `distinct_id`: PostHog's user identifier. Used for PERSON LINKING only, not access control.

This prevents users from accessing others' chats by knowing their email.
"""

import uuid
import hashlib
import logging
from datetime import datetime
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

from posthog.api.utils import on_permitted_recording_domain
from posthog.models import Team
from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status

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
    if not distinct_id:
        raise ValidationError("distinct_id is required")

    distinct_id = str(distinct_id)

    if len(distinct_id) > 400:
        raise ValidationError("distinct_id too long")

    return distinct_id


def sanitize_message_content(content: str) -> str:
    if not content or not content.strip():
        raise ValidationError("message content is required")

    if len(content) > 5000:
        raise ValidationError("Message too long (max 5000 chars)")

    return content.strip()


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


def validate_ticket_id(ticket_id: Optional[str]) -> str:
    """Validate ticket_id is a valid UUID."""
    if not ticket_id:
        raise ValidationError("ticket_id is required")

    try:
        uuid.UUID(ticket_id)
    except ValueError:
        raise ValidationError("ticket_id must be a valid UUID")

    return ticket_id


def validate_pagination(limit_str: Optional[str], offset_str: Optional[str], max_limit: int = 500) -> tuple[int, int]:
    """Validate and parse pagination parameters."""
    try:
        limit = int(limit_str) if limit_str else 100
    except (ValueError, TypeError):
        raise ValidationError("limit must be a valid integer")

    try:
        offset = int(offset_str) if offset_str else 0
    except (ValueError, TypeError):
        raise ValidationError("offset must be a valid integer")

    if limit < 1 or limit > max_limit:
        raise ValidationError(f"limit must be between 1 and {max_limit}")
    if offset < 0:
        raise ValidationError("offset must be non-negative")

    return limit, offset


def validate_timestamp(timestamp: Optional[str]) -> Optional[str]:
    """Validate ISO timestamp format."""
    if not timestamp:
        return None

    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValidationError("Invalid timestamp format, expected ISO 8601")

    return timestamp


def validate_status_filter(status_filter: Optional[str]) -> Optional[str]:
    """Validate status filter against allowed values."""
    if not status_filter:
        return None

    valid_statuses = [s.value for s in Status]
    if status_filter not in valid_statuses:
        raise ValidationError(f"Invalid status, must be one of: {', '.join(valid_statuses)}")

    return status_filter


def validate_origin(request: Request, team: Team) -> bool:
    """
    Validate request origin to prevent token reuse on unauthorized domains.
    Checks against team.conversations_settings.widget_domains if configured.
    Empty list = allow all domains.
    """
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
            raw_ticket_id = request.data.get("ticket_id")
            ticket_id = validate_ticket_id(raw_ticket_id) if raw_ticket_id else None

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
            validate_ticket_id(ticket_id)
            widget_session_id = validate_widget_session_id(request.query_params.get("widget_session_id"))
            after = validate_timestamp(request.query_params.get("after"))
            limit, _ = validate_pagination(request.query_params.get("limit"), None, max_limit=500)
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
            status_filter = validate_status_filter(request.query_params.get("status"))
            limit, offset = validate_pagination(
                request.query_params.get("limit", "10"), request.query_params.get("offset"), max_limit=50
            )
        except ValidationError:
            logger.exception("Validation error in WidgetTicketsView")
            return Response({"error": "Invalid request data"}, status=status.HTTP_400_BAD_REQUEST)

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
            validate_ticket_id(ticket_id)
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
