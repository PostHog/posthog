"""Let a logged-in user's agent draft a ticket to PostHog support, for the person to approve.

The agent shows the person the draft in chat. When the person approves it there, the agent sends it,
and the server posts it to PostHog support as the person. Otherwise the person opens the review link
and sends it from the web app's support form. Reading a draft and claiming it for that form accept
browser sessions only.
"""

from __future__ import annotations

import re
from typing import Any, cast

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import MCP_TRANSPORT_EVENT_SOURCES, get_event_source, report_user_action, sanitize_header_value
from posthog.models.user import User
from posthog.rate_limit import PostHogSupportDraftCreateThrottle

from products.conversations.backend.permissions import SessionAuthenticationOnly
from products.conversations.backend.services.posthog_support import (
    AGENT_CLAIMANT,
    DraftedVia,
    FilingReason,
    SentVia,
    SupportDraftStore,
    SupportTicketDraft,
    TicketPermission,
    check_ticket_permission,
    compose_ticket_message,
)
from products.conversations.backend.services.posthog_support_widget import (
    PostHogSupportWidgetClient,
    SentSupportTicket,
    SupportTicketNotSent,
    SupportTicketOutcomeUnknown,
    resolve_support_widget_target,
)

DRAFT_ID_PATTERN = r"[0-9a-f-]{36}"
# Any caller can set the MCP headers, and the ids end up in a ticket note the person cannot edit, so a
# value that could carry words is dropped.
MCP_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def _mcp_id(value: str | None) -> str | None:
    value = sanitize_header_value(value)
    return value if value and MCP_ID_PATTERN.fullmatch(value) else None


class PostHogSupportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What went wrong.")


# The field caps add up to well under the support widget's 10,000-character message limit, with room
# for the headings and the ticket context the web app appends, so a valid draft always sends.
class PostHogSupportDraftCreateSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=100,
        help_text=(
            "A short title that names the problem, such as 'Experiment exposures split 90/10 instead of 50/50'. "
            "It opens the ticket, and ticket lists show it, so don't start it with 'Request'."
        ),
    )
    request = serializers.CharField(
        max_length=2000,
        help_text=(
            "The whole ask, in the person's voice. Open with what happened in one sentence, with the numbers and "
            "dates. Then add the action they need in one sentence, or list every question the docs did not answer, "
            "numbered in the person's order, with every part of each question. When they heard your answer and "
            "still want a human, give your answer in one sentence, as yours."
        ),
    )
    details = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        help_text=(
            "Markdown bullets of facts support needs: the project and the region, a link to each object involved, "
            "SDK and version, and every required detail for the kind of request, such as a deletion query and its "
            "count. Link each object on its name, such as '- Experiment: [Checkout test](<link>)', and put the "
            "region on its own line. Take links from _posthogUrl. No guesses."
        ),
    )
    already_checked = serializers.CharField(
        max_length=1500,
        required=False,
        allow_blank=True,
        help_text=(
            "Markdown bullets of what was already checked, each with its result. Start a docs check with 'Docs:' and "
            "link the page on its title, "
            "a lookup you ran in this conversation with '<your name> checked:', and a step the person took with "
            "'I tried:'. List only your checks that bear on the open questions, because support can look up the "
            "rest of your calls. Never write a number the person gave you as your own check."
        ),
    )
    error = serializers.CharField(
        max_length=1500,
        required=False,
        allow_blank=True,
        help_text=(
            "The exact text of an error the person saw, and its top frames. A lookup of yours that failed goes in "
            "already_checked. Remove any credential and say that you removed it."
        ),
    )
    filing_reason = serializers.ChoiceField(
        choices=FilingReason.choices,
        help_text=(
            "Why a human at PostHog should look at this. Your own conclusion that it is a PostHog bug is not a reason. "
            "Use billing_question only when the ticket is about billing or usage, not for a billing question asked in "
            "passing in a ticket about something else."
        ),
    )
    agent_name = serializers.RegexField(
        r"^[\w .\-]{1,40}$",
        required=False,
        allow_blank=True,
        help_text="Name of the agent or client drafting the ticket, such as Claude Code or Codex.",
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        data["message"] = compose_ticket_message(
            title=data["title"],
            request=data["request"],
            details=data.get("details"),
            already_checked=data.get("already_checked"),
            error=data.get("error"),
        )
        return data


class PostHogSupportDraftSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Draft id.")
    message = serializers.CharField(help_text="Ticket text exactly as the person will see it in the support form.")
    ticket_context = serializers.CharField(
        help_text="Note filed under the ticket for support, saying an agent drafted it and why."
    )
    expires_at = serializers.IntegerField(help_text="Unix time after which the draft is gone if nobody sent it.")
    billing_question = serializers.BooleanField(
        help_text="True when the draft is a billing or usage question, which the person can send on any plan."
    )
    can_send = serializers.BooleanField(
        help_text="True when the person's plan lets them send this ticket. Offer to send it only when this is true."
    )
    review_url = serializers.CharField(
        help_text="Link the person opens in their browser to review, edit and send the ticket."
    )
    next_step = serializers.CharField(help_text="What to tell the person now.")


class PostHogSupportSentTicketSerializer(serializers.Serializer):
    ticket_id = serializers.CharField(help_text="Id of the ticket PostHog support received.")
    ticket_number = serializers.IntegerField(
        allow_null=True, help_text="The ticket's number, which the person can quote to support."
    )
    tickets_url = serializers.CharField(help_text="Page in PostHog where the person reads support's replies.")
    next_step = serializers.CharField(help_text="What to tell the person now.")


class _SendFromWebAppOnly(SessionAuthenticationOnly):
    message = "Only the person can open a draft or send it from the PostHog web app."


COMMUNITY_URL = "https://posthog.com/questions"

NEXT_STEP_BY_PERMISSION = {
    TicketPermission.ALLOWED: (
        "Nothing has been sent. Show the person the full message above and ask whether to send it to PostHog "
        "support. Call posthog-support-draft-send only after they say yes in this conversation. If they want "
        "to edit it or send it themselves, give them review_url. Do not tell them the ticket was filed."
    ),
    TicketPermission.PLAN_EXCLUDES_SUPPORT: (
        "Nothing has been sent. Their plan doesn't include support tickets, so don't offer to send it. Show "
        f"them the message and tell them they can ask the community at {COMMUNITY_URL}. Mention upgrading "
        "only if they ask."
    ),
    TicketPermission.PLAN_UNKNOWN: (
        "Nothing has been sent. PostHog couldn't check their plan, so don't offer to send it from here. Show "
        "them the message and give them review_url to send it from PostHog."
    ),
}


def _claimant(request: ValidatedRequest) -> str | None:
    return request.session.session_key if hasattr(request, "session") else None


def _draft_not_found() -> Response:
    return Response({"detail": "Draft not found or expired."}, status=status.HTTP_404_NOT_FOUND)


class PostHogSupportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "posthog_support"
    # The draft reads and the claim are left out on purpose: the scope check refuses tokens on
    # unlisted actions, so only a browser session can open a draft or send it from the web app.
    scope_object_write_actions = ["create_draft", "send_draft"]
    pagination_class = None

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "create_draft":
            return [PostHogSupportDraftCreateThrottle(), *super().get_throttles()]
        return super().get_throttles()

    @property
    def _user(self) -> User:
        return cast(User, self.request.user)

    def _draft_store(self) -> SupportDraftStore:
        return SupportDraftStore(self._user.pk)

    def _tickets_url(self) -> str:
        return f"{settings.SITE_URL}/project/{self.team_id}/my-tickets"

    def _permission(self, draft: SupportTicketDraft) -> TicketPermission:
        return check_ticket_permission(self.organization, self._user, draft.filing_reason)

    def _draft_response(self, draft: SupportTicketDraft, status_code: int = status.HTTP_200_OK) -> Response:
        permission = self._permission(draft)
        data = PostHogSupportDraftSerializer(
            {
                "id": draft.id,
                "message": draft.message,
                "ticket_context": draft.ticket_context(SentVia.WEB_APP),
                "expires_at": draft.expires_at,
                "billing_question": draft.filing_reason == FilingReason.BILLING_QUESTION,
                "can_send": permission == TicketPermission.ALLOWED,
                "review_url": f"{self._tickets_url()}?support_draft={draft.id}",
                "next_step": NEXT_STEP_BY_PERMISSION[permission],
            }
        ).data
        return Response(data, status=status_code)

    def _sent_response(self, ticket: SentSupportTicket) -> Response:
        data = PostHogSupportSentTicketSerializer(
            {
                "ticket_id": ticket.ticket_id,
                "ticket_number": ticket.ticket_number,
                "tickets_url": self._tickets_url(),
                "next_step": (
                    "The ticket is with PostHog support. Tell the person its number, and that support's replies "
                    "show up at tickets_url and in the Support panel in PostHog. Don't promise a response time."
                ),
            }
        ).data
        return Response(data, status=status.HTTP_200_OK)

    def _send_failed(self, draft: SupportTicketDraft, reason: str, detail: str, status_code: int) -> Response:
        report_user_action(
            self._user,
            "posthog support draft send failed",
            {"draft_id": draft.id, "filing_reason": draft.filing_reason, "reason": reason},
            team=self.team,
        )
        return Response({"detail": detail}, status=status_code)

    @validated_request(
        request_serializer=PostHogSupportDraftCreateSerializer,
        responses={
            201: OpenApiResponse(response=PostHogSupportDraftSerializer),
            429: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Draft a PostHog support ticket for the person to approve",
        description=(
            "Saves a draft ticket to PostHog support. It does not send it. The person approves it in chat, so "
            "the agent sends it with the send endpoint, or opens review_url to edit it and send it from the "
            "PostHog web app."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="drafts")
    def create_draft(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        mcp_session_id = _mcp_id(request.headers.get("X-Posthog-Mcp-Session-Id"))
        mcp_conversation_id = _mcp_id(request.headers.get("X-Posthog-Mcp-Conversation-Id"))
        drafted_via = DraftedVia.MCP if get_event_source(request) in MCP_TRANSPORT_EVENT_SOURCES else DraftedVia.API
        draft = self._draft_store().create(
            message=data["message"],
            filing_reason=data["filing_reason"],
            drafted_via=drafted_via,
            mcp_session_id=mcp_session_id,
            mcp_conversation_id=mcp_conversation_id,
        )
        report_user_action(
            self._user,
            "posthog support draft created",
            {
                "draft_id": draft.id,
                "filing_reason": draft.filing_reason,
                "agent_name": data.get("agent_name") or None,
                "authenticated_with": type(request.successful_authenticator).__name__,
                "drafted_via": drafted_via.value,
                # The MCP server records each tool call under these same ids, so support can follow a
                # ticket's draft id back to every call the agent made before it drafted the ticket.
                "mcp_session_id": mcp_session_id,
                "mcp_conversation_id": mcp_conversation_id,
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
        description="A draft that has not been sent yet. Browser sessions only.",
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path=rf"drafts/(?P<draft_id>{DRAFT_ID_PATTERN})",
        permission_classes=[_SendFromWebAppOnly],
    )
    def retrieve_draft(self, request: ValidatedRequest, draft_id: str, *args: Any, **kwargs: Any) -> Response:
        draft = self._draft_store().get(draft_id, claimant=_claimant(request))
        if draft is None:
            return _draft_not_found()
        return self._draft_response(draft)

    @validated_request(
        responses={
            204: None,
            403: OpenApiResponse(response=PostHogSupportErrorSerializer),
            404: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Claim a draft for the person to send",
        description=(
            "Called by the web app right before it sends the person's ticket. One browser session can claim a "
            "draft, and can claim it again to retry, so a review link opened elsewhere cannot file it twice. "
            "Browser sessions only."
        ),
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path=rf"drafts/(?P<draft_id>{DRAFT_ID_PATTERN})/claim",
        permission_classes=[_SendFromWebAppOnly],
    )
    def claim_draft(self, request: ValidatedRequest, draft_id: str, *args: Any, **kwargs: Any) -> Response:
        store = self._draft_store()
        claimant = _claimant(request)
        draft = store.get(draft_id, claimant=claimant)
        if draft is None or claimant is None or not store.claim(draft_id, claimant):
            return _draft_not_found()
        # The ticket context carries the draft id, which joins this event to the ticket support receives.
        report_user_action(
            self._user,
            "posthog support draft submitted",
            {"draft_id": draft_id, "filing_reason": draft.filing_reason, "sent_via": SentVia.WEB_APP.value},
            team=self.team,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        responses={
            200: OpenApiResponse(response=PostHogSupportSentTicketSerializer),
            403: OpenApiResponse(response=PostHogSupportErrorSerializer),
            404: OpenApiResponse(response=PostHogSupportErrorSerializer),
            409: OpenApiResponse(response=PostHogSupportErrorSerializer),
            502: OpenApiResponse(response=PostHogSupportErrorSerializer),
            503: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Send a drafted ticket to PostHog support after the person approved it",
        description=(
            "Posts the draft to PostHog support as the person, and returns the ticket. Call it only after the "
            "person saw the full ticket and approved sending it. A draft becomes at most one ticket: calling "
            "again returns the same ticket, and a draft sent from the review link can't be sent here."
        ),
    )
    @action(methods=["POST"], detail=False, url_path=rf"drafts/(?P<draft_id>{DRAFT_ID_PATTERN})/send")
    def send_draft(self, request: ValidatedRequest, draft_id: str, *args: Any, **kwargs: Any) -> Response:
        store = self._draft_store()
        if (sent := store.sent_ticket(draft_id)) is not None:
            return self._sent_response(sent)
        draft = store.get(draft_id, claimant=AGENT_CLAIMANT)
        if draft is None:
            return Response(
                {"detail": "Draft not found, expired, or already sent from PostHog."},
                status=status.HTTP_404_NOT_FOUND,
            )

        permission = self._permission(draft)
        if permission == TicketPermission.PLAN_EXCLUDES_SUPPORT:
            return self._send_failed(
                draft,
                permission.value,
                "Nothing was sent, because their plan doesn't include support tickets. Tell them they can ask "
                f"the community at {COMMUNITY_URL}.",
                status.HTTP_403_FORBIDDEN,
            )
        if permission == TicketPermission.PLAN_UNKNOWN:
            return self._send_failed(
                draft,
                permission.value,
                "Nothing was sent, because PostHog couldn't check their plan. Give them the draft's review_url "
                "to send it from PostHog.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        may_be_sent = (
            "The ticket may already be with PostHog support, so don't send it again. Ask the person to check "
            f"their tickets at {self._tickets_url()}."
        )
        if not store.claim(draft_id, AGENT_CLAIMANT):
            return _draft_not_found()
        if not store.start_send(draft_id):
            return self._send_failed(draft, "already_sending", may_be_sent, status.HTTP_409_CONFLICT)
        try:
            ticket = PostHogSupportWidgetClient(resolve_support_widget_target()).send_ticket(
                self._user, draft.outgoing_message(SentVia.CHAT)
            )
        except SupportTicketNotSent:
            store.cancel_send(draft_id)
            store.release(draft_id, AGENT_CLAIMANT)
            return self._send_failed(
                draft,
                "not_sent",
                "Nothing was sent, because PostHog support couldn't take the ticket. Try again in a moment, "
                "or give the person the draft's review_url to send it from PostHog.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except SupportTicketOutcomeUnknown:
            return self._send_failed(draft, "outcome_unknown", may_be_sent, status.HTTP_502_BAD_GATEWAY)

        store.record_sent(draft_id, ticket)
        report_user_action(
            self._user,
            "posthog support draft submitted",
            {
                "draft_id": draft_id,
                "filing_reason": draft.filing_reason,
                "sent_via": SentVia.CHAT.value,
                "ticket_id": ticket.ticket_id,
            },
            team=self.team,
        )
        return self._sent_response(ticket)
