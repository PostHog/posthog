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

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.models import Team
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.conversations.backend.api.ticket_actions import (
    TicketActionMessageResponseSerializer,
    TicketActionMessageSerializer,
    handle_ticket_get,
    handle_ticket_message,
    handle_ticket_patch,
    wants_first_customer_message_text,
)
from products.conversations.backend.metrics import TICKET_ACTION_AUTH_COUNTER
from products.conversations.backend.services.email_thread_ingestion import EmailAddress
from products.conversations.backend.services.workflow_email_ingestion import (
    get_verified_workflow_sender,
    ingest_workflow_email,
    is_workflow_email_capture_enabled,
)

CONVERSATIONS_TICKETS_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.CONVERSATIONS_TICKETS,
    settings_name="CONVERSATIONS_TICKETS_JWT_SECRETS",
)


class ConversationsTicketJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = CONVERSATIONS_TICKETS_PURPOSE


CONVERSATIONS_WORKFLOW_EMAILS_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.CONVERSATIONS_WORKFLOW_EMAILS,
    settings_name="CONVERSATIONS_WORKFLOW_EMAILS_JWT_SECRETS",
)


class ConversationsWorkflowEmailJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = CONVERSATIONS_WORKFLOW_EMAILS_PURPOSE


class WorkflowEmailAddressSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=400, help_text="Email address used for this send.")
    name = serializers.CharField(default="", allow_blank=True, max_length=400, help_text="Rendered display name.")


class WorkflowEmailCaptureSerializer(serializers.Serializer):
    source_id = serializers.CharField(
        max_length=512, help_text="Stable Workflow invocation ID for retry deduplication."
    )
    provider_message_id = serializers.RegexField(
        regex=r"\A[A-Za-z0-9-]{1,250}\Z",
        trim_whitespace=False,
        help_text="SES SendEmail response MessageId, without angle brackets.",
    )
    email_integration_id = serializers.IntegerField(
        min_value=1, help_text="Verified email integration for this project."
    )
    sent_at = serializers.DateTimeField(help_text="SES acceptance time.")
    sender = WorkflowEmailAddressSerializer(help_text="Rendered verified sender.")
    to = WorkflowEmailAddressSerializer(help_text="Primary recipient.")
    cc = serializers.ListField(
        child=WorkflowEmailAddressSerializer(),
        required=False,
        max_length=49,
        help_text="Visible copy recipients, excluding BCC.",
    )
    subject = serializers.CharField(
        max_length=998, allow_blank=True, trim_whitespace=False, help_text="Rendered email subject."
    )
    body_plain = serializers.CharField(
        max_length=200000, allow_blank=True, trim_whitespace=False, help_text="Rendered plain-text email body."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "bcc" in self.initial_data:
            raise serializers.ValidationError({"bcc": "BCC must not be captured."})
        return attrs


class WorkflowEmailCaptureResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="created, existing, skipped_disabled, or skipped_unmatched.")


class InternalWorkflowEmailView(APIView):
    authentication_classes = [ConversationsWorkflowEmailJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(request=WorkflowEmailCaptureSerializer, responses={200: WorkflowEmailCaptureResponseSerializer})
    def post(self, request: Request, team_id: str) -> Response:
        serializer = WorkflowEmailCaptureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        claims = cast(dict[str, Any], request.auth or {})
        if claims.get("source_id") != payload["source_id"]:
            return Response({"error": "Service token does not grant access to this email"}, status=403)

        team = Team.objects.get(id=claims["team_id"])
        if not is_workflow_email_capture_enabled(team):
            return Response(WorkflowEmailCaptureResponseSerializer({"status": "skipped_disabled"}).data)
        sender = EmailAddress(**payload["sender"])
        if not get_verified_workflow_sender(
            team_id=team.id, integration_id=payload["email_integration_id"], sender_email=sender.email
        ):
            return Response({"error": "Email integration not found"}, status=404)

        result = ingest_workflow_email(
            team=team,
            source_id=payload["source_id"],
            provider_message_id=payload["provider_message_id"],
            sent_at=payload["sent_at"],
            sender=sender,
            to_recipient=EmailAddress(**payload["to"]),
            cc_recipients=tuple(EmailAddress(**address) for address in payload.get("cc", [])),
            subject=payload["subject"],
            body_plain=payload["body_plain"],
        )
        return Response(
            WorkflowEmailCaptureResponseSerializer(
                {"status": "skipped_unmatched" if result is None else "created" if result.created else "existing"}
            ).data
        )


class InternalTicketView(APIView):
    """
    GET /api/projects/<team_id>/internal/conversations/tickets/<ticket_id> — Fetch ticket data
    PATCH /api/projects/<team_id>/internal/conversations/tickets/<ticket_id> — Update ticket fields
    POST /api/projects/<team_id>/internal/conversations/tickets/<ticket_id> — Post a reply or private note

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
        return handle_ticket_get(
            team, ticket_id, include_first_customer_message_text=wants_first_customer_message_text(request)
        )

    def patch(self, request: Request, team_id: str, ticket_id: uuid.UUID) -> Response:
        team, error = _check_ticket_access(request, ticket_id)
        if error:
            return error
        assert team is not None
        TICKET_ACTION_AUTH_COUNTER.labels(auth_method="scoped_jwt", http_method="patch").inc()
        return handle_ticket_patch(request, team, ticket_id)

    @extend_schema(
        request=TicketActionMessageSerializer,
        responses={
            status.HTTP_200_OK: TicketActionMessageResponseSerializer,
            status.HTTP_201_CREATED: TicketActionMessageResponseSerializer,
        },
    )
    def post(self, request: Request, team_id: str, ticket_id: uuid.UUID) -> Response:
        team, error = _check_ticket_access(request, ticket_id)
        if error:
            return error
        assert team is not None
        TICKET_ACTION_AUTH_COUNTER.labels(auth_method="scoped_jwt", http_method="post").inc()
        return handle_ticket_message(request, team, ticket_id)


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
