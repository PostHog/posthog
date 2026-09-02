"""
Widget API endpoints for the Conversations product.

These endpoints are public (authenticated via public token) and used by the posthog-js widget.

Security model:
- `widget_session_id`: Random UUID generated client-side, stored in localStorage. Used for ACCESS CONTROL.
- `distinct_id`: PostHog's user identifier. Used for PERSON LINKING only, not access control.
- `identity_distinct_id` + `identity_hash`: HMAC-signed identity for verified users (opt-in).

Anonymous users are controlled by widget_session_id. Verified users are controlled by distinct_id.
"""

import uuid
import hashlib
import logging
from dataclasses import field as dataclass_field
from typing import Literal

from django.db.models import F, Q

from prometheus_client import Counter
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import WidgetAuthentication
from posthog.dataclasses import frozen
from posthog.event_usage import report_team_action
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.comment import Comment
from posthog.rate_limit import WIDGET_POLL_THROTTLES, WIDGET_WRITE_THROTTLES

from products.conversations.backend.api.serializers import (
    WIDGET_TICKETS_DEFAULT_LIMIT,
    WidgetMarkReadSerializer,
    WidgetMessageSerializer,
    WidgetMessagesQuerySerializer,
    WidgetTicketsQuerySerializer,
    validate_origin,
)
from products.conversations.backend.cache import (
    get_cached_messages,
    get_cached_tickets,
    get_identity_tickets_cache_namespace,
    get_person_distinct_ids,
    invalidate_identity_tickets_cache,
    invalidate_tickets_cache,
    invalidate_unread_count_cache,
    set_cached_messages,
    set_cached_tickets,
)
from products.conversations.backend.models import SigningSecret, Ticket
from products.conversations.backend.models.constants import ChannelDetail
from products.conversations.backend.services.identity import (
    canonicalize_claim_value,
    identity_claim_has_expired,
    verify_identity_claim_hash,
    verify_identity_hash,
)

logger = logging.getLogger(__name__)

IdentityClaimField = Literal["email"]
TicketOwnershipMatch = Literal["distinct_id", "email"]


@frozen
class _IdentitySecret:
    source: Literal["signing_secret", "legacy_token", "legacy_backup"]
    secret: str = dataclass_field(repr=False)


IDENTITY_VERIFICATION_COUNTER = Counter(
    "conversations_identity_verification_total",
    "Widget identity verification attempts by outcome and which stored secret matched",
    labelnames=["outcome", "source"],
)

SIGNING_SECRET_STALE_COUNTER = Counter(
    "conversations_signing_secret_stale_total",
    "Signing secret rows skipped because they do not match the team's current secret API token",
)


class IdentityVerificationFailed(Exception):
    """Raised when identity fields are present but HMAC verification fails."""

    # Surfaced to the widget. Keep it generic so a signature mismatch reveals nothing.
    public_error = "Forbidden"


class IdentityVerificationNotConfigured(IdentityVerificationFailed):
    """Raised when the team has no secret API key to verify identity hashes against."""

    # The widget API is AllowAny — reachable by anyone with the public widget token — so the
    # response can't name the cause without leaking config state. Stays "Forbidden" (inherited);
    # the specific reason is logged server-side for the team's own admins to see.


def _identity_secrets(team: Team) -> list[_IdentitySecret]:
    """Credentials to verify a hash against, preferred store first.

    The conversations signing secret is where this credential is moving; the legacy
    Team.secret_api_token stays a fallback so teams that predate the backfill keep
    verifying. The rotation backup is accepted too, so hashes signed with the previous
    secret survive a rotation.

    While the legacy column exists it remains the revocation authority: rotating and then
    deleting the backup has to actually revoke the old key. The row is compared against the
    current secret API token only — a row still holding the previous key matches the rotation
    backup, so counting that as agreement would report a team whose sync failed as fully
    migrated. Verification is unaffected: such a row still verifies via `legacy_backup`.
    """
    legacy_secrets: list[_IdentitySecret] = []
    if team.secret_api_token:
        legacy_secrets.append(_IdentitySecret(source="legacy_token", secret=team.secret_api_token))
    if team.secret_api_token_backup:
        legacy_secrets.append(_IdentitySecret(source="legacy_backup", secret=team.secret_api_token_backup))

    secrets: list[_IdentitySecret] = []
    signing_secret = SigningSecret.objects.for_team(team.id).first()
    if signing_secret and signing_secret.secret:
        if not legacy_secrets or signing_secret.secret == team.secret_api_token:
            secrets.append(_IdentitySecret(source="signing_secret", secret=signing_secret.secret))
        else:
            SIGNING_SECRET_STALE_COUNTER.inc()
            logger.warning("Conversations signing secret is stale, skipping it", extra={"team_id": team.id})

    return secrets + legacy_secrets


def _request_identity_secrets(data: dict, team: Team) -> list[_IdentitySecret] | None:
    if not data.get("identity_distinct_id") or not data.get("identity_hash"):
        return None
    return _identity_secrets(team)


def _verify_identity(
    data: dict,
    team: Team,
    secrets: list[_IdentitySecret] | None = None,
) -> str | None:
    """
    Verify HMAC identity fields against the team's signing secret, falling back to the
    legacy secret API token and its rotation backup.
    Returns the verified distinct_id, or None if identity fields not present.
    Raises IdentityVerificationFailed if identity was attempted but failed.
    An explicit empty secrets list means no credential is configured; None resolves it here.
    """
    distinct_id = data.get("identity_distinct_id")
    hash_value = data.get("identity_hash")
    if not distinct_id or not hash_value:
        return None

    resolved_secrets = secrets if secrets is not None else _identity_secrets(team)
    if not resolved_secrets:
        logger.warning(
            "Identity verification attempted but team has no signing secret or legacy token",
            extra={"team_id": team.id},
        )
        IDENTITY_VERIFICATION_COUNTER.labels(outcome="not_configured", source="none").inc()
        raise IdentityVerificationNotConfigured("Team has no signing secret")

    for identity_secret in resolved_secrets:
        if verify_identity_hash(distinct_id, hash_value, identity_secret.secret):
            IDENTITY_VERIFICATION_COUNTER.labels(outcome="verified", source=identity_secret.source).inc()
            return distinct_id

    IDENTITY_VERIFICATION_COUNTER.labels(outcome="invalid_hash", source="none").inc()
    raise IdentityVerificationFailed("Invalid identity hash")


def _verify_identity_claim(
    data: dict,
    team: Team,
    verified_distinct_id: str,
    *,
    field: IdentityClaimField = "email",
    secrets: list[_IdentitySecret] | None = None,
) -> str | None:
    """Verify a signed identity claim for one named field, returning its canonical value.

    The claim wire format is `identity_<field>` + `identity_hash_<field>` +
    `identity_exp_<field>`. The hash uses the same secrets as the base identity and binds the
    claim to its verified distinct ID and expiry. A missing, expired, or invalid claim returns
    None so the caller falls back to distinct ID access.
    """
    value = data.get(f"identity_{field}")
    hash_value = data.get(f"identity_hash_{field}")
    expires_at = data.get(f"identity_exp_{field}")
    if not value or not hash_value or not expires_at:
        return None
    if identity_claim_has_expired(expires_at):
        IDENTITY_VERIFICATION_COUNTER.labels(outcome="claim_expired", source="none").inc()
        return None

    resolved_secrets = secrets if secrets is not None else _identity_secrets(team)
    if not resolved_secrets:
        return None

    try:
        canonical = canonicalize_claim_value(field, value)
    except ValueError:
        IDENTITY_VERIFICATION_COUNTER.labels(outcome="claim_invalid", source="none").inc()
        return None

    for identity_secret in resolved_secrets:
        if verify_identity_claim_hash(
            verified_distinct_id,
            field,
            canonical,
            hash_value,
            identity_secret.secret,
            expires_at=expires_at,
        ):
            IDENTITY_VERIFICATION_COUNTER.labels(outcome="claim_verified", source=identity_secret.source).inc()
            return canonical

    IDENTITY_VERIFICATION_COUNTER.labels(outcome="claim_invalid", source="none").inc()
    return None


# PostHog treats Zendesk as the source of record for imported requester emails. Other NULL
# identities can be client-supplied legacy widget data and must never bridge by email.
_EMAIL_BRIDGE_TRUSTED = Q(identity_verified=True) | (
    Q(identity_verified__isnull=True) & Q(zendesk_ticket_id__isnull=False)
)


def _identity_ticket_filter(team: Team, verified_distinct_id: str, verified_email: str | None) -> Q:
    """Q matching every ticket the verified viewer owns, across channels.

    The viewer's own person distinct_ids cover widget tickets. Other channels key the
    requester by email in distinct_id (Slack, email, Zendesk), so also match the viewer's
    attested email against server-attested tickets only. The email is a signed claim verified
    upstream, never a mutable analytics property.
    """
    all_ids = get_person_distinct_ids(team.id, verified_distinct_id)
    match = Q(distinct_id__in=all_ids)
    if verified_email:
        match |= _EMAIL_BRIDGE_TRUSTED & Q(distinct_id__iexact=verified_email)
    return match


def _viewer_ticket_match(
    team: Team, verified_distinct_id: str, ticket: Ticket, verified_email: str | None
) -> TicketOwnershipMatch | None:
    """Return how the verified viewer owns this ticket, mirroring _identity_ticket_filter."""
    allowed_ids = get_person_distinct_ids(team.id, verified_distinct_id)
    if ticket.distinct_id in allowed_ids:
        return "distinct_id"
    if not verified_email or not ticket.distinct_id:
        return None
    is_trusted_email = ticket.identity_verified is True or (
        ticket.identity_verified is None and ticket.zendesk_ticket_id is not None
    )
    if not is_trusted_email:
        return None
    # Keep this no wider than _identity_ticket_filter's iexact lookup, which does not trim.
    if ticket.distinct_id.lower() == verified_email:
        return "email"
    return None


def _identity_tickets_cache_key(cache_namespace: str, verified_distinct_id: str, verified_email: str | None) -> str:
    base_key = f"iv:{cache_namespace}:{verified_distinct_id}"
    if not verified_email:
        return base_key
    email_digest = hashlib.sha256(verified_email.encode()).hexdigest()
    return f"{base_key}:email:{email_digest}"


class WidgetMessageView(APIView):
    """
    POST /api/conversations/v1/widget/message
    Create a new message in a ticket (or create ticket if first message).

    Security: Access controlled by widget_session_id (random UUID), not distinct_id.
    """

    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = WIDGET_WRITE_THROTTLES

    def post(self, request: Request) -> Response:
        """Handle incoming message from widget."""

        team: Team | None = request.auth  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
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
            try:
                # Track rejected submissions server-side so they're queryable even when the
                # client-side event is blocked (ad blockers, network drops). Field names and
                # value lengths only — never message content. An over-long auto-captured
                # session_context value (e.g. current_url) is a known rejection cause.
                # This endpoint is public and unauthenticated, so session_context is
                # attacker-controlled: bound both the number of fields and the key length we
                # record so a request stuffed with many keys can't inflate the event payload.
                raw_session_context = request.data.get("session_context")
                session_context_field_count = len(raw_session_context) if isinstance(raw_session_context, dict) else 0
                session_context_field_lengths = {}
                if isinstance(raw_session_context, dict):
                    for key, value in list(raw_session_context.items())[:20]:
                        if isinstance(key, str) and isinstance(value, str):
                            session_context_field_lengths[key[:100]] = len(value)
                report_team_action(
                    team,
                    "support ticket send failed",
                    {
                        "channel_source": "widget",
                        "reason": "validation_error",
                        "error_fields": sorted(serializer.errors.keys()),
                        "session_context_field_count": session_context_field_count,
                        "session_context_field_lengths": session_context_field_lengths,
                    },
                )
            except Exception as e:
                capture_exception(e)
            return Response(
                {"error": "Invalid request data", "details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            identity_secrets = _request_identity_secrets(serializer.validated_data, team)
            verified_distinct_id = _verify_identity(serializer.validated_data, team, identity_secrets)
        except IdentityVerificationFailed as e:
            return Response({"error": e.public_error}, status=status.HTTP_403_FORBIDDEN)

        if verified_distinct_id is not None:
            distinct_id = verified_distinct_id
            # Deterministic widget_session_id from the HMAC (for DB storage)
            widget_session_id = str(uuid.UUID(serializer.validated_data["identity_hash"][:32]))
        elif "widget_session_id" in serializer.validated_data:
            widget_session_id = str(serializer.validated_data["widget_session_id"])
            distinct_id = serializer.validated_data["distinct_id"]
        else:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

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

                ownership_match: TicketOwnershipMatch | None = None
                if verified_distinct_id is not None:
                    verified_email = _verify_identity_claim(
                        serializer.validated_data, team, verified_distinct_id, secrets=identity_secrets
                    )
                    ownership_match = _viewer_ticket_match(team, verified_distinct_id, ticket, verified_email)
                    if ownership_match is None:
                        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
                else:
                    # CRITICAL: Verify ticket belongs to this widget_session_id (NOT distinct_id)
                    if ticket.widget_session_id != widget_session_id:
                        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

                # Only HMAC-verified requests may (re)bind a ticket's distinct_id.
                # Anonymous → identified continuity is still handled by person merging.
                if ownership_match == "distinct_id" and ticket.distinct_id != distinct_id:
                    ticket.distinct_id = distinct_id

                # Update traits if provided
                if traits:
                    ticket.anonymous_traits.update(traits)

                # Update session data if provided
                if session_id:
                    ticket.session_id = session_id
                if session_context:
                    ticket.session_context.update(session_context)

                # HMAC-verified requests are server-attested — mark the identity trusted.
                if ownership_match == "distinct_id":
                    ticket.identity_verified = True

                # Increment unread count for team (customer sent a message)
                ticket.unread_team_count = F("unread_team_count") + 1
                ticket.save(
                    update_fields=[
                        "distinct_id",
                        "anonymous_traits",
                        "session_id",
                        "session_context",
                        "unread_team_count",
                        "identity_verified",
                        "updated_at",
                    ]
                )
                ticket.refresh_from_db()

            except Ticket.DoesNotExist:
                return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            # No ticket_id provided - always create a new ticket
            conversations_settings = team.conversations_settings or {}
            widget_channel_detail = (
                ChannelDetail.WIDGET_EMBEDDED
                if conversations_settings.get("widget_enabled")
                else ChannelDetail.WIDGET_API
            )
            ticket = Ticket.objects.create_with_number(
                team=team,
                widget_session_id=widget_session_id,
                distinct_id=distinct_id,
                channel_source="widget",
                channel_detail=widget_channel_detail,
                status="new",
                anonymous_traits=traits,
                unread_team_count=1,
                session_id=session_id,
                session_context=session_context,
                identity_verified=verified_distinct_id is not None,
            )

            try:
                report_team_action(team, "support ticket created", {"channel_source": ticket.channel_source})
            except Exception as e:
                capture_exception(e, {"ticket_id": str(ticket.id)})

        # Create message
        comment = Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=message_content,
            item_context={"author_type": "customer", "distinct_id": distinct_id, "is_private": False},
        )

        # tickets + messages caches are invalidated by the post_save signal
        # via transaction.on_commit (see signals.py). Only unread_count needs
        # explicit invalidation here since the signal doesn't cover it.
        invalidate_unread_count_cache(team.id)

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
    throttle_classes = WIDGET_POLL_THROTTLES

    def get(self, request: Request, ticket_id: str) -> Response:
        """Get messages for a ticket."""

        team: Team | None = request.auth  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
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

        after = query_serializer.validated_data.get("after")
        limit = query_serializer.validated_data["limit"]

        # Get ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id, team=team)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        # Verify ownership: identity mode uses distinct_id, legacy uses widget_session_id
        try:
            identity_secrets = _request_identity_secrets(query_serializer.validated_data, team)
            verified_distinct_id = _verify_identity(query_serializer.validated_data, team, identity_secrets)
        except IdentityVerificationFailed as e:
            return Response({"error": e.public_error}, status=status.HTTP_403_FORBIDDEN)

        if verified_distinct_id is not None:
            verified_email = _verify_identity_claim(
                query_serializer.validated_data, team, verified_distinct_id, secrets=identity_secrets
            )
            if _viewer_ticket_match(team, verified_distinct_id, ticket, verified_email) is None:
                return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        elif "widget_session_id" in query_serializer.validated_data:
            widget_session_id = str(query_serializer.validated_data["widget_session_id"])
            if ticket.widget_session_id != widget_session_id:
                return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        else:
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
        # Use exclude + isnull to match _is_private_message() identity check:
        # - Exclude only exact boolean True
        # - Include everything else (False, None, missing key, weird values)
        # The isnull handles SQL NULL semantics where ~Q alone would exclude missing keys
        messages_query = messages_query.filter(
            ~Q(item_context__is_private=True) | Q(item_context__is_private__isnull=True)
        )

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
                    "rich_content": m.rich_content,
                    "author_type": author_type,
                    "author_name": author_name,
                    "created_at": m.created_at.isoformat(),
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
    throttle_classes = WIDGET_POLL_THROTTLES

    def get(self, request: Request) -> Response:
        """List tickets for a widget_session_id."""

        team: Team | None = request.auth  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        if not team:
            return Response({"error": "Authentication required"}, status=status.HTTP_403_FORBIDDEN)

        # Validate query parameters
        query_serializer = WidgetTicketsQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {"error": "Invalid request data", "details": query_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            identity_secrets = _request_identity_secrets(query_serializer.validated_data, team)
            verified_distinct_id = _verify_identity(query_serializer.validated_data, team, identity_secrets)
        except IdentityVerificationFailed as e:
            return Response({"error": e.public_error}, status=status.HTTP_403_FORBIDDEN)

        verified_email: str | None = None
        if verified_distinct_id is not None:
            verified_email = _verify_identity_claim(
                query_serializer.validated_data, team, verified_distinct_id, secrets=identity_secrets
            )
            cache_namespace = get_identity_tickets_cache_namespace(team.id)
            cache_key_id = (
                _identity_tickets_cache_key(cache_namespace, verified_distinct_id, verified_email)
                if cache_namespace
                else None
            )
        elif "widget_session_id" in query_serializer.validated_data:
            cache_key_id = str(query_serializer.validated_data["widget_session_id"])
        else:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        status_filter = query_serializer.validated_data.get("status")
        limit = query_serializer.validated_data["limit"]
        offset = query_serializer.validated_data["offset"]

        # Only cache the default first page (WIDGET_TICKETS_DEFAULT_LIMIT, offset=0)
        # used by widget polling. Custom limit/offset must bypass the cache — its
        # key doesn't include limit/offset, so serving it for other page sizes
        # returns the wrong slice (e.g. ?limit=2 getting the full cached page back).
        cacheable_key = cache_key_id if offset == 0 and limit == WIDGET_TICKETS_DEFAULT_LIMIT else None
        if cacheable_key is not None:
            cached = get_cached_tickets(team.id, cacheable_key, status_filter)
            if cached is not None:
                return Response(cached)

        # Build query
        if verified_distinct_id is not None:
            tickets_query = Ticket.objects.filter(team=team).filter(
                _identity_ticket_filter(team, verified_distinct_id, verified_email)
            )
        else:
            tickets_query = Ticket.objects.filter(team=team, widget_session_id=cache_key_id)

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
                    "ticket_number": ticket.ticket_number,
                    "status": ticket.status,
                    "unread_count": ticket.unread_customer_count,  # Unread messages for customer
                    "last_message": ticket.last_message_text,  # Now from denormalized field
                    "last_message_at": ticket.last_message_at.isoformat() if ticket.last_message_at else None,
                    "message_count": ticket.message_count,
                    "created_at": ticket.created_at.isoformat(),
                }
            )

        response_data = {"count": total_count, "results": ticket_list}

        # Cache first page (skip empty results to avoid stale cache after restore/migration)
        if cacheable_key is not None and total_count > 0:
            set_cached_tickets(team.id, cacheable_key, response_data, status_filter)

        return Response(response_data)


class WidgetMarkReadView(APIView):
    """
    POST /api/conversations/v1/widget/messages/<ticket_id>/read
    Mark all messages in a ticket as read by the customer.

    This resets unread_customer_count to 0.
    """

    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = WIDGET_WRITE_THROTTLES

    def post(self, request: Request, ticket_id: str) -> Response:
        """Mark ticket messages as read by customer."""

        team: Team | None = request.auth  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
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

        # Get ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id, team=team)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        # Verify ownership: identity mode uses distinct_id, legacy uses widget_session_id
        try:
            identity_secrets = _request_identity_secrets(body_serializer.validated_data, team)
            verified_distinct_id = _verify_identity(body_serializer.validated_data, team, identity_secrets)
        except IdentityVerificationFailed as e:
            return Response({"error": e.public_error}, status=status.HTTP_403_FORBIDDEN)

        if verified_distinct_id is not None:
            verified_email = _verify_identity_claim(
                body_serializer.validated_data, team, verified_distinct_id, secrets=identity_secrets
            )
            if _viewer_ticket_match(team, verified_distinct_id, ticket, verified_email) is None:
                return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
            cache_namespace = get_identity_tickets_cache_namespace(team.id)
            if cache_namespace:
                cache_invalidation_keys = [
                    _identity_tickets_cache_key(cache_namespace, verified_distinct_id, verified_email)
                ]
                if verified_email:
                    cache_invalidation_keys.append(
                        _identity_tickets_cache_key(cache_namespace, verified_distinct_id, None)
                    )
                rotate_identity_cache = False
            else:
                cache_invalidation_keys = []
                rotate_identity_cache = True
        elif "widget_session_id" in body_serializer.validated_data:
            widget_session_id = str(body_serializer.validated_data["widget_session_id"])
            if ticket.widget_session_id != widget_session_id:
                return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
            cache_invalidation_keys = [widget_session_id]
            rotate_identity_cache = False
        else:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Reset unread count for customer
        if ticket.unread_customer_count > 0:
            ticket.unread_customer_count = 0
            ticket.save(update_fields=["unread_customer_count", "updated_at"])
            if rotate_identity_cache:
                invalidate_identity_tickets_cache(team.id)
            for cache_invalidation_key in cache_invalidation_keys:
                invalidate_tickets_cache(team.id, cache_invalidation_key)

        return Response({"success": True, "unread_count": 0})
