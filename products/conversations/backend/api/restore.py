"""
Restore API endpoints for the Conversations product.

These endpoints enable users to recover their tickets on a new browser/device
using secure email-based restore tokens.

Security:
- Tokens are one-time use with short TTL (60min)
- Only SHA-256 hashes of tokens are stored
- Generic responses prevent email enumeration
- Rate limited to prevent abuse
"""

import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import WidgetAuthentication
from posthog.models import Team
from posthog.rate_limit import (
    RestoreRedeemThrottle,
    RestoreRequestThrottle,
    WidgetTeamThrottle,
    WidgetUserBurstThrottle,
)
from posthog.tasks.email import send_conversation_restore_email

from products.conversations.backend.api.serializers import validate_origin, validate_url_domain
from products.conversations.backend.cache import invalidate_tickets_cache
from products.conversations.backend.services.restore import RestoreService

logger = logging.getLogger(__name__)


def _build_restore_url(base_url: str, token: str) -> str:
    """
    Build the restore URL by appending the token to the user's site URL.

    Preserves the base URL's path and existing query params, adding ph_conv_restore.
    """
    parsed = urlparse(base_url)
    # Parse existing query params and add the restore token
    query_params = parse_qs(parsed.query)
    query_params["ph_conv_restore"] = [token]
    # Rebuild the URL with the new query string
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, ""))


class RestoreRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    request_url = serializers.URLField(max_length=2048)


class RestoreRedeemSerializer(serializers.Serializer):
    restore_token = serializers.CharField(min_length=40, max_length=50)  # 43 chars expected
    widget_session_id = serializers.UUIDField()


class WidgetRestoreRequestView(APIView):
    """
    POST /api/conversations/v1/widget/restore/request
    Request a restore link to recover tickets from another browser/device.

    Always returns {"ok": true} to prevent email enumeration.
    If the email has associated tickets, a restore link will be sent.
    """

    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [RestoreRequestThrottle, WidgetUserBurstThrottle, WidgetTeamThrottle]

    def post(self, request: Request) -> Response:
        team: Team | None = request.auth  # type: ignore[assignment]
        if not team:
            return Response({"error": "Authentication required"}, status=status.HTTP_403_FORBIDDEN)

        if not validate_origin(request, team):
            return Response({"error": "Origin not allowed"}, status=status.HTTP_403_FORBIDDEN)

        serializer = RestoreRequestSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Validation error in RestoreRequestView", extra={"errors": serializer.errors})
            return Response(
                {"error": "Invalid request data", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = serializer.validated_data["email"]
        request_url = serializer.validated_data["request_url"]

        # Validate request_url domain against team's allowlist to prevent phishing
        if not validate_url_domain(request_url, team):
            logger.warning(
                "Restore request_url domain not in allowlist", extra={"domain": urlparse(request_url).netloc}
            )
            return Response({"error": "URL domain not allowed"}, status=status.HTTP_403_FORBIDDEN)

        # Request restore link (may return None if no tickets found)
        raw_token = RestoreService.request_restore_link(team, email)

        if raw_token:
            # Build restore URL by appending token to the user's site URL
            restore_url = _build_restore_url(request_url, raw_token)
            send_conversation_restore_email.delay(
                email=email,
                team_id=team.id,
                restore_url=restore_url,
            )

        # Always return ok to prevent email enumeration
        return Response({"ok": True})


class WidgetRestoreRedeemView(APIView):
    """
    POST /api/conversations/v1/widget/restore
    Redeem a restore token to migrate tickets to the current browser session.

    Returns the migration result including status and migrated ticket IDs.
    """

    authentication_classes = [WidgetAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [RestoreRedeemThrottle, WidgetUserBurstThrottle, WidgetTeamThrottle]

    def post(self, request: Request) -> Response:
        team: Team | None = request.auth  # type: ignore[assignment]
        if not team:
            return Response({"error": "Authentication required"}, status=status.HTTP_403_FORBIDDEN)

        if not validate_origin(request, team):
            return Response({"error": "Origin not allowed"}, status=status.HTTP_403_FORBIDDEN)

        serializer = RestoreRedeemSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Validation error in RestoreRedeemView", extra={"errors": serializer.errors})
            return Response(
                {"error": "Invalid request data", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_token = serializer.validated_data["restore_token"]
        widget_session_id = str(serializer.validated_data["widget_session_id"])

        # Redeem token
        result = RestoreService.redeem_token(
            team=team,
            raw_token=raw_token,
            widget_session_id=widget_session_id,
        )

        # Invalidate tickets cache if migration succeeded
        if result.status == "success" and result.migrated_ticket_ids:
            invalidate_tickets_cache(team.id, widget_session_id)

        # Build response
        response_data: dict = {"status": result.status}
        if result.code:
            response_data["code"] = result.code
        if result.widget_session_id:
            response_data["widget_session_id"] = result.widget_session_id
        if result.migrated_ticket_ids:
            response_data["migrated_ticket_ids"] = result.migrated_ticket_ids

        return Response(response_data)
