"""Tickets with PostHog's own support team, opened by the signed-in user or their agent.

Mounted under /api/projects/<team_id>/posthog_support/tickets/. The project in the URL only
tells support which project the question is about; the ticket lives in PostHog's support inbox.
"""

from typing import Any, cast

from django.conf import settings
from django.db import models

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.rate_limit import (
    PostHogSupportTicketCreateBurstThrottle,
    PostHogSupportTicketCreateSustainedThrottle,
    PostHogSupportTicketReadThrottle,
)

from products.conversations.backend.models.constants import TicketStatus
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


class PostHogSupportTicketListQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=TicketStatus.choices,
        required=False,
        help_text="Only return tickets with this status.",
    )
    limit = serializers.IntegerField(
        required=False, default=20, min_value=1, max_value=100, help_text="Number of tickets to return."
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Number of tickets to skip.")


class PostHogSupportTicketMessagesQuerySerializer(serializers.Serializer):
    after = serializers.DateTimeField(
        required=False,
        help_text=(
            "Only return messages sent after this time. When `has_more` is true, pass the `created_at` of the "
            "last message to read the next page."
        ),
    )


class PostHogSupportTicketSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Ticket ID. Pass it to posthog-support-ticket-get to read the messages.")
    ticket_number = serializers.IntegerField(help_text="Ticket number that PostHog support uses in replies.")
    status = serializers.ChoiceField(choices=TicketStatus.choices, help_text="Current status of the ticket.")
    unread_count = serializers.IntegerField(help_text="Support replies the user has not read yet.")
    last_message = serializers.CharField(allow_null=True, help_text="Start of the newest message in the ticket.")
    last_message_at = serializers.DateTimeField(allow_null=True, help_text="When the newest message arrived.")
    message_count = serializers.IntegerField(help_text="Number of messages in the ticket.")
    created_at = serializers.DateTimeField(help_text="When the ticket was opened.")


# `list` returns one `{count, results}` object, so the schema must not wrap it in an array.
@extend_schema_serializer(many=False)
class PostHogSupportTicketListSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total number of the user's tickets that match the filter.")
    results = PostHogSupportTicketSummarySerializer(many=True, help_text="The user's tickets, newest first.")


class PostHogSupportMessageSerializer(serializers.Serializer):
    author_type = serializers.CharField(
        help_text="Who wrote it: `customer` for the user, `support` for PostHog staff, `AI` for the support assistant."
    )
    author_name = serializers.CharField(help_text="Display name of the author.")
    content = serializers.CharField(help_text="Message text.")
    created_at = serializers.DateTimeField(help_text="When the message was sent.")


class PostHogSupportTicketDetailSerializer(serializers.Serializer):
    ticket_id = serializers.UUIDField(help_text="Ticket ID.")
    ticket_status = serializers.ChoiceField(choices=TicketStatus.choices, help_text="Current status of the ticket.")
    messages = PostHogSupportMessageSerializer(many=True, help_text="Messages the user can see, oldest first.")
    has_more = serializers.BooleanField(help_text="True when the ticket has more messages than this response holds.")


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


@frozen
class _SupportCaller:
    client: PostHogSupportClient
    identity: SupportIdentity
    user: User


class PostHogSupportTicketViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "posthog_support"
    lookup_value_regex = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    pagination_class = None
    serializer_class = CreatePostHogSupportTicketSerializer

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "create":
            return [PostHogSupportTicketCreateBurstThrottle(), PostHogSupportTicketCreateSustainedThrottle()]
        # Reads share the support project's widget budget with every browser, so one agent must not use it up.
        return [PostHogSupportTicketReadThrottle()]

    def _support(self) -> _SupportCaller:
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
        return _SupportCaller(client=client, identity=identity, user=user)

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
        caller = self._support()
        user = caller.user
        data = cast(dict[str, Any], request.validated_data)
        team = self.team
        try:
            result = caller.client.create_ticket(
                caller.identity,
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

    @validated_request(
        query_serializer=PostHogSupportTicketListQuerySerializer,
        responses={
            200: OpenApiResponse(response=PostHogSupportTicketListSerializer, description="The user's tickets."),
            403: OpenApiResponse(description="Not available for this user or credential."),
            502: OpenApiResponse(description="The support inbox did not answer."),
            503: OpenApiResponse(description="This instance has no support inbox."),
        },
        summary="List your PostHog support tickets",
        description=(
            "List the signed-in user's tickets with the PostHog support team, newest first, from every channel the "
            "user verified: in-app, API, email and Slack. Use it to check whether support has replied."
        ),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        client, identity, _user = self._support()
        query = cast(dict[str, Any], request.validated_query_data)  # type: ignore[attr-defined]
        try:
            result = client.list_tickets(
                identity, status=query.get("status"), limit=query["limit"], offset=query["offset"]
            )
        except PostHogSupportRequestFailed:
            raise SupportInboxFailed()
        return Response(PostHogSupportTicketListSerializer(result).data)

    @validated_request(
        query_serializer=PostHogSupportTicketMessagesQuerySerializer,
        responses={
            200: OpenApiResponse(response=PostHogSupportTicketDetailSerializer, description="The ticket's messages."),
            403: OpenApiResponse(description="Not available for this user or credential."),
            404: OpenApiResponse(description="No ticket with this ID belongs to the user."),
            502: OpenApiResponse(description="The support inbox did not answer."),
            503: OpenApiResponse(description="This instance has no support inbox."),
        },
        summary="Read a PostHog support ticket",
        description=(
            "Read the status and the messages of one of the signed-in user's tickets with PostHog support. "
            "Internal notes of the support team are not included."
        ),
    )
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        client, identity, _user = self._support()
        try:
            query = cast(dict[str, Any], request.validated_query_data)  # type: ignore[attr-defined]
            result = client.get_ticket(identity, kwargs["pk"], after=query.get("after"))
        except PostHogSupportRequestFailed as e:
            # The inbox answers 403 for a ticket of another person, so both mean "not yours" here.
            if e.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
                raise NotFound("No PostHog support ticket with this ID belongs to you.")
            raise SupportInboxFailed()
        return Response(PostHogSupportTicketDetailSerializer(result).data)


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
