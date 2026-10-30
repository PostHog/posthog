"""Tickets with PostHog's own support team, opened by the signed-in user or their agent.

Mounted under /api/projects/<team_id>/posthog_support/tickets/. The project in the URL only
tells support which project the question is about; the ticket lives in PostHog's support inbox.
"""

from typing import Any, cast

from django.conf import settings
from django.db import models

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.rate_limit import PostHogSupportTicketCreateBurstThrottle, PostHogSupportTicketCreateSustainedThrottle

from products.conversations.backend.services.posthog_support import (
    PostHogSupportClient,
    PostHogSupportRequestFailed,
    PostHogSupportUnavailable,
    SupportIdentity,
)

POSTHOG_SUPPORT_AGENT_TICKETS_FLAG = "posthog-support-agent-tickets"

MAX_SECTION_LENGTH = 4000
# Matches the max_length of WidgetMessageSerializer.message, which every ticket passes through.
WIDGET_MESSAGE_MAX_LENGTH = 10000


class PostHogSupportRequestType(models.TextChoices):
    QUESTION = "question", "Question"
    BUG = "bug", "Bug"
    DATA_DELETION = "data_deletion", "Data deletion"
    BILLING = "billing", "Billing"
    OTHER = "other", "Other"


class CreatePostHogSupportTicketSerializer(serializers.Serializer):
    request_type = serializers.ChoiceField(
        choices=PostHogSupportRequestType.choices,
        help_text=(
            "What kind of help this is. Use `data_deletion` only to ask PostHog staff to permanently delete "
            "events, and fill `deletion_query`, `expected_event_count` and `deletion_consent`."
        ),
    )
    subject = serializers.CharField(
        max_length=200,
        help_text="One line that says what the problem or question is.",
    )
    description = serializers.CharField(
        max_length=MAX_SECTION_LENGTH,
        help_text=(
            "The full problem or question in plain text. Include event names, flag keys, SDK names and versions, "
            "and links to the PostHog pages involved. Do not include secrets, API keys or personal data."
        ),
    )
    expected = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        help_text="What you expected to happen.",
    )
    actual = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        help_text="What happened instead, with exact error messages.",
    )
    already_tried = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        help_text="Docs pages read and steps already tried, so support does not repeat them.",
    )
    deletion_query = serializers.CharField(
        max_length=MAX_SECTION_LENGTH,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text=(
            "For `data_deletion` only: a HogQL query with a time range that selects exactly the events to delete. "
            "Sent as raw text, so paste it unchanged."
        ),
    )
    expected_event_count = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="For `data_deletion` only: the number of events the deletion query returns now.",
    )
    deletion_consent = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "For `data_deletion` only: true confirms that the user wants these events permanently deleted. "
            "Ask the user before you set it. Deleted events cannot be restored."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["request_type"] == PostHogSupportRequestType.DATA_DELETION:
            errors: dict[str, str] = {}
            if not (attrs.get("deletion_query") or "").strip():
                errors["deletion_query"] = "A data deletion request needs the query that selects the events."
            if attrs.get("expected_event_count") is None:
                errors["expected_event_count"] = "A data deletion request needs the current event count."
            if not attrs.get("deletion_consent"):
                errors["deletion_consent"] = "A data deletion request needs explicit consent from the user."
            if errors:
                raise ValidationError(errors)
        if len(build_ticket_message(attrs)) > WIDGET_MESSAGE_MAX_LENGTH:
            raise ValidationError(
                {
                    "description": (
                        f"The ticket is longer than {WIDGET_MESSAGE_MAX_LENGTH} characters in total. "
                        "Shorten the description or the other text fields."
                    )
                }
            )
        return attrs


class PostHogSupportTicketCreatedSerializer(serializers.Serializer):
    ticket_id = serializers.UUIDField(help_text="ID of the new ticket in PostHog's support inbox.")
    ticket_status = serializers.CharField(help_text="Status of the ticket, `new` right after creation.")
    created_at = serializers.DateTimeField(help_text="When support received the first message.")


class SupportInboxUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "This PostHog instance has no PostHog support inbox."
    default_code = "support_inbox_unavailable"


class SupportInboxFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The PostHog support inbox did not answer. Try again later."
    default_code = "support_inbox_failed"


def build_ticket_message(data: dict[str, Any]) -> str:
    request_type = PostHogSupportRequestType(data["request_type"])
    sections = [data["subject"].strip(), "", data["description"].strip()]
    for label, key in (("Expected", "expected"), ("Actual", "actual"), ("Already tried", "already_tried")):
        value = (data.get(key) or "").strip()
        if value:
            sections += ["", f"{label}:", value]
    if request_type == PostHogSupportRequestType.DATA_DELETION:
        sections += [
            "",
            "Deletion query:",
            data["deletion_query"],
            "",
            f"Expected event count: {data['expected_event_count']}",
            "Consent to permanent deletion: yes",
        ]
    return "\n".join(sections)


class PostHogSupportTicketViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "posthog_support"
    pagination_class = None
    serializer_class = CreatePostHogSupportTicketSerializer

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "create":
            return [PostHogSupportTicketCreateBurstThrottle(), PostHogSupportTicketCreateSustainedThrottle()]
        return super().get_throttles()

    def _support(self) -> tuple[PostHogSupportClient, SupportIdentity, User]:
        user = self.request.user
        if not isinstance(user, User):
            raise PermissionDenied("PostHog support tickets need a signed-in user, not a project key.")
        if not _agent_tickets_enabled(user):
            raise PermissionDenied("PostHog support tickets through the API are not available yet.")
        try:
            client = PostHogSupportClient.from_settings()
        except PostHogSupportUnavailable:
            raise SupportInboxUnavailable()
        identity = SupportIdentity(
            distinct_id=str(user.distinct_id),
            verified_email=user.email if user.is_email_verified is True else None,
        )
        return client, identity, user

    @validated_request(
        request_serializer=CreatePostHogSupportTicketSerializer,
        responses={
            201: OpenApiResponse(response=PostHogSupportTicketCreatedSerializer, description="Ticket opened."),
            403: OpenApiResponse(description="Not available for this user or credential."),
            502: OpenApiResponse(description="The support inbox did not accept the ticket."),
            503: OpenApiResponse(description="This instance has no support inbox."),
        },
        summary="Open a ticket with PostHog support",
        description=(
            "Open a support ticket with the PostHog support team as the signed-in user. The ticket is verified as "
            "sent by this user and is about the project in the URL. Search the docs first: only open a ticket when "
            "the docs and the project's own data do not answer the question."
        ),
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        client, identity, user = self._support()
        data = cast(dict[str, Any], request.validated_data)  # type: ignore[attr-defined]
        team = self.team
        try:
            result = client.create_ticket(
                identity,
                message=build_ticket_message(data),
                traits={"name": user.first_name or "", "email": user.email},
                session_context={
                    "source": "posthog_support_api",
                    "request_type": data["request_type"],
                    "project_id": str(team.id),
                    "organization_id": str(team.organization_id),
                    "instance_url": settings.SITE_URL,
                },
            )
        except PostHogSupportRequestFailed:
            raise SupportInboxFailed()

        report_user_action(user, "posthog support ticket created", {"request_type": data["request_type"]}, team=team)
        return Response(
            PostHogSupportTicketCreatedSerializer(
                {
                    "ticket_id": result["ticket_id"],
                    "ticket_status": result["ticket_status"],
                    "created_at": result["created_at"],
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )


def _agent_tickets_enabled(user: User) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                POSTHOG_SUPPORT_AGENT_TICKETS_FLAG,
                str(user.distinct_id),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False
