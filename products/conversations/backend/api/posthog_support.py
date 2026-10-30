"""Let a logged-in user's agent read their PostHog support tickets and draft new ones.

The agent can draft a ticket but never send one. Sending happens only in the web app, where the
person reads the draft in the support form and submits it themselves. The draft endpoints that
finish a send accept browser sessions only, so no API key or OAuth token can complete one.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.rate_limit import PostHogSupportDraftCreateThrottle, PostHogSupportReadThrottle

from products.conversations.backend.models.constants import TicketStatus
from products.conversations.backend.permissions import SessionAuthenticationOnly
from products.conversations.backend.services.posthog_support import (
    DraftCreateInProgress,
    FilingReason,
    PostHogSupportClient,
    PostHogSupportTicketNotFound,
    PostHogSupportUnavailable,
    SupportDraftStore,
    SupportTicketDraft,
    TooManyOpenDrafts,
    build_support_identity,
    compose_draft_message,
    resolve_support_widget_target,
)


class PostHogSupportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What went wrong.")


class PostHogSupportTicketsQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=TicketStatus.choices,
        required=False,
        help_text="Only return tickets with this status.",
    )
    limit = serializers.IntegerField(
        required=False, default=20, min_value=1, max_value=100, help_text="How many tickets to return."
    )
    offset = serializers.IntegerField(
        required=False, default=0, min_value=0, help_text="How many tickets to skip, for paging."
    )


class PostHogSupportTicketSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Ticket id. Pass it to the ticket messages endpoint to read the thread.")
    ticket_number = serializers.IntegerField(allow_null=True, help_text="Ticket number shown to the person.")
    status = serializers.ChoiceField(choices=TicketStatus.choices, help_text="Where the ticket is in support's queue.")
    unread_count = serializers.IntegerField(help_text="Replies from PostHog support the person has not read yet.")
    last_message = serializers.CharField(allow_null=True, help_text="Text of the latest message on the ticket.")
    last_message_at = serializers.CharField(allow_null=True, help_text="ISO 8601 time of the latest message.")
    message_count = serializers.IntegerField(help_text="Number of messages visible to the person.")
    created_at = serializers.CharField(help_text="ISO 8601 time the ticket was created.")


class PostHogSupportTicketListSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total number of matching tickets.")
    results = PostHogSupportTicketSerializer(many=True, help_text="The person's tickets, newest first.")


class PostHogSupportMessageSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Message id.")
    content = serializers.CharField(help_text="Message text.")
    author_type = serializers.CharField(
        help_text="customer for the person, support for a PostHog support engineer, AI for PostHog's assistant."
    )
    author_name = serializers.CharField(help_text="Display name of the author.")
    created_at = serializers.CharField(help_text="ISO 8601 time the message was sent.")


class PostHogSupportThreadSerializer(serializers.Serializer):
    ticket_id = serializers.CharField(help_text="Ticket id.")
    ticket_status = serializers.ChoiceField(choices=TicketStatus.choices, help_text="Current ticket status.")
    messages = PostHogSupportMessageSerializer(many=True, help_text="Messages in the thread, oldest first.")
    has_more = serializers.BooleanField(help_text="True when the thread has more messages than were returned.")


class PostHogSupportDraftCreateSerializer(serializers.Serializer):
    customer_words = serializers.CharField(
        max_length=4000,
        help_text=(
            "The person's own description of the problem, quoted verbatim from what they wrote. "
            "Do not paraphrase it, and do not add your own diagnosis."
        ),
    )
    filing_reason = serializers.ChoiceField(
        choices=FilingReason.choices,
        help_text=(
            "Why a human should look at this. Draft only when the person asked for support, the problem involves "
            "account, billing or data only PostHog can see, there is a reproducible error you confirmed but cannot "
            "explain, or the person disagrees with your answer. Your own conclusion that it is a PostHog bug is "
            "not a reason."
        ),
    )
    details = serializers.CharField(
        max_length=8000,
        required=False,
        allow_blank=True,
        help_text=(
            "Facts the person gave or that you observed directly: exact error text, URLs, event and property names, "
            "the insight, flag or other object involved, SDK and version, when it started, and what they expected "
            "to happen. No guesses or conclusions."
        ),
    )
    already_tried = serializers.CharField(
        max_length=4000,
        required=False,
        allow_blank=True,
        help_text="What the person and you already checked or tried, so support can judge the investigation.",
    )
    agent_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text="Name of the agent or client drafting the ticket, for example Claude Code or Codex.",
    )


class PostHogSupportDraftSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Draft id.")
    message = serializers.CharField(help_text="Ticket text exactly as the person will see it in the support form.")
    filing_reason = serializers.ChoiceField(choices=FilingReason.choices, help_text="Why the agent drafted it.")
    agent_name = serializers.CharField(allow_null=True, help_text="Agent or client that drafted it.")
    expires_at = serializers.IntegerField(help_text="Unix time after which the draft is gone if nobody sent it.")
    ticket_context = serializers.CharField(
        help_text="Note filed under the ticket for support, saying an agent drafted it and why."
    )
    review_url = serializers.CharField(
        help_text="Link the person must open in their browser to review, edit and send the ticket."
    )
    sent = serializers.BooleanField(help_text="Always false. Only the person can send the ticket, from review_url.")
    next_step = serializers.CharField(help_text="What to tell the person now.")


class _SendFromWebAppOnly(SessionAuthenticationOnly):
    message = "Only the person can send a support ticket, from the PostHog web app."


def _draft_not_found() -> Response:
    return Response({"detail": "Draft not found or expired."}, status=status.HTTP_404_NOT_FOUND)


class PostHogSupportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "posthog_support"
    scope_object_read_actions = ["tickets", "ticket_messages", "retrieve_draft"]
    scope_object_write_actions = ["create_draft", "discard_draft", "claim_draft"]
    pagination_class = None

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "create_draft":
            return [PostHogSupportDraftCreateThrottle(), *super().get_throttles()]
        if self.action in ("tickets", "ticket_messages"):
            return [PostHogSupportReadThrottle(), *super().get_throttles()]
        return super().get_throttles()

    @property
    def _user(self) -> User:
        return cast(User, self.request.user)

    def _client(self) -> PostHogSupportClient:
        return PostHogSupportClient(resolve_support_widget_target(), build_support_identity(self._user))

    def _draft_store(self) -> SupportDraftStore:
        return SupportDraftStore(self._user.pk)

    def _draft_response(self, draft: SupportTicketDraft, status_code: int = status.HTTP_200_OK) -> Response:
        data = PostHogSupportDraftSerializer(
            {
                **asdict(draft),
                "ticket_context": draft.ticket_context,
                "review_url": f"{settings.SITE_URL}/project/{self.team_id}/my-tickets?support_draft={draft.id}",
                "sent": False,
                "next_step": (
                    "Nothing has been sent. Show the person the draft text above and give them review_url. "
                    "They open it in PostHog, check and edit the ticket, and send it themselves. Do not tell them "
                    "the ticket was filed."
                ),
            }
        ).data
        return Response(data, status=status_code)

    @validated_request(
        query_serializer=PostHogSupportTicketsQuerySerializer,
        responses={
            200: OpenApiResponse(response=PostHogSupportTicketListSerializer),
            503: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="List your PostHog support tickets",
        description="Tickets the logged-in user has raised with PostHog support, newest first.",
    )
    @action(methods=["GET"], detail=False, url_path="tickets")
    def tickets(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        try:
            page = self._client().list_tickets(status=query.get("status"), limit=query["limit"], offset=query["offset"])
        except PostHogSupportUnavailable as e:
            return Response({"detail": str(e)}, status=503)
        return Response(PostHogSupportTicketListSerializer(page).data)

    @validated_request(
        responses={
            200: OpenApiResponse(response=PostHogSupportThreadSerializer),
            404: OpenApiResponse(response=PostHogSupportErrorSerializer),
            503: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Read one of your PostHog support tickets",
        description="The messages on one of the logged-in user's PostHog support tickets, oldest first.",
    )
    @action(methods=["GET"], detail=False, url_path=r"tickets/(?P<ticket_id>[0-9a-f-]{36})/messages")
    def ticket_messages(self, request: ValidatedRequest, ticket_id: str, *args: Any, **kwargs: Any) -> Response:
        try:
            thread = self._client().get_thread(ticket_id)
        except PostHogSupportTicketNotFound:
            return Response({"detail": "Ticket not found."}, status=status.HTTP_404_NOT_FOUND)
        except PostHogSupportUnavailable as e:
            return Response({"detail": str(e)}, status=503)
        return Response(PostHogSupportThreadSerializer(thread).data)

    @validated_request(
        request_serializer=PostHogSupportDraftCreateSerializer,
        responses={
            201: OpenApiResponse(response=PostHogSupportDraftSerializer),
            429: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Draft a PostHog support ticket for the person to send",
        description=(
            "Saves a draft ticket to PostHog support. It does not send it. The person opens review_url, "
            "checks and edits the ticket, and sends it from the PostHog web app."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="drafts")
    def create_draft(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        try:
            draft = self._draft_store().create(
                message=compose_draft_message(
                    customer_words=data["customer_words"],
                    details=data.get("details"),
                    already_tried=data.get("already_tried"),
                ),
                filing_reason=data["filing_reason"],
                agent_name=data.get("agent_name") or None,
            )
        except DraftCreateInProgress:
            return Response(
                {"detail": "Another draft is being saved. Try again in a few seconds."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except TooManyOpenDrafts:
            return Response(
                {
                    "detail": "This person already has several drafts waiting for review. "
                    "Ask them to send or discard those first."
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        report_user_action(
            self._user,
            "posthog support draft created",
            {
                "draft_id": draft.id,
                "filing_reason": draft.filing_reason,
                "agent_name": draft.agent_name,
                "authenticated_with": type(request.successful_authenticator).__name__,
            },
            team=self.team,
        )
        return self._draft_response(draft, status.HTTP_201_CREATED)

    @validated_request(
        responses={
            200: OpenApiResponse(response=PostHogSupportDraftSerializer),
            404: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Get a PostHog support ticket draft",
        description="A draft that has not been sent or discarded yet.",
    )
    @action(methods=["GET"], detail=False, url_path=r"drafts/(?P<draft_id>[0-9a-f-]{36})")
    def retrieve_draft(self, request: ValidatedRequest, draft_id: str, *args: Any, **kwargs: Any) -> Response:
        draft = self._draft_store().get(draft_id)
        if draft is None:
            return _draft_not_found()
        return self._draft_response(draft)

    @validated_request(
        responses={204: None, 404: OpenApiResponse(response=PostHogSupportErrorSerializer)},
        summary="Discard a PostHog support ticket draft",
        description="Deletes a draft without sending it.",
    )
    @action(methods=["POST"], detail=False, url_path=r"drafts/(?P<draft_id>[0-9a-f-]{36})/discard")
    def discard_draft(self, request: ValidatedRequest, draft_id: str, *args: Any, **kwargs: Any) -> Response:
        if not self._draft_store().delete(draft_id):
            return _draft_not_found()
        report_user_action(self._user, "posthog support draft discarded", {"draft_id": draft_id}, team=self.team)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        responses={
            204: None,
            403: OpenApiResponse(response=PostHogSupportErrorSerializer),
            404: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Claim a draft for the person to send",
        description=(
            "Called by the web app right before it sends the person's ticket. Each draft can be claimed once, "
            "so a review link opened twice cannot file the same ticket twice. Browser sessions only."
        ),
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path=r"drafts/(?P<draft_id>[0-9a-f-]{36})/claim",
        # Added to the mixin's own team and scope checks, which stay in place.
        permission_classes=[_SendFromWebAppOnly],
    )
    def claim_draft(self, request: ValidatedRequest, draft_id: str, *args: Any, **kwargs: Any) -> Response:
        store = self._draft_store()
        draft = store.get(draft_id)
        if draft is None or not store.delete(draft_id):
            return _draft_not_found()
        # The ticket context carries the draft id, which joins this event to the ticket support receives.
        report_user_action(
            self._user,
            "posthog support draft submitted",
            {"draft_id": draft_id, "filing_reason": draft.filing_reason, "agent_name": draft.agent_name},
            team=self.team,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
