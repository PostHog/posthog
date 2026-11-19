"""Let a logged-in user's agent draft a ticket to PostHog support, for the person to review and send.

The agent can draft a ticket but never send one. The person opens the draft in the web app and sends
it from the support form. Reading a draft and claiming it for sending accept browser sessions only,
so no API key or OAuth token can complete a send.
"""

from __future__ import annotations

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
from posthog.rate_limit import PostHogSupportDraftCreateThrottle

from products.conversations.backend.permissions import SessionAuthenticationOnly
from products.conversations.backend.services.posthog_support import (
    DraftCreateInProgress,
    FilingReason,
    SupportDraftStore,
    SupportTicketDraft,
    TooManyOpenDrafts,
    compose_ticket_message,
)

DRAFT_ID_PATTERN = r"[0-9a-f-]{36}"


class PostHogSupportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What went wrong.")


# The field caps add up to well under the support widget's 10,000-character message limit, with room
# for the headings and the ticket context the web app appends, so a valid draft always sends.
class PostHogSupportDraftCreateSerializer(serializers.Serializer):
    request = serializers.CharField(
        max_length=1000,
        help_text=(
            "What the person needs PostHog to do or answer, in one to three sentences, in their own words. "
            "Put each question they asked on its own line."
        ),
    )
    details = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        help_text=(
            "Markdown bullets of facts support needs: the project name, ID, region and link, links to the objects "
            "involved, SDK and version, and every required detail for the kind of request, such as a deletion "
            "query and its count. Take links from _posthogUrl. No guesses."
        ),
    )
    already_checked = serializers.CharField(
        max_length=1500,
        required=False,
        allow_blank=True,
        help_text=(
            "Markdown bullets of what was already checked, each with its result. Start a docs check with 'Docs:', "
            "one of yours with '<your name> checked:', and one of the person's with 'I tried:'."
        ),
    )
    left_for_support = serializers.CharField(
        max_length=500,
        help_text="The one thing only PostHog can do or confirm, such as 'Delete the 3,817 events this query returns'.",
    )
    error = serializers.CharField(
        max_length=1500,
        required=False,
        allow_blank=True,
        help_text="The exact error text and its top frames. Remove any credential and say that you removed it.",
    )
    filing_reason = serializers.ChoiceField(
        choices=FilingReason.choices,
        help_text=(
            "Why a human at PostHog should look at this. Your own conclusion that it is a PostHog bug is not a reason."
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
            request=data["request"],
            details=data.get("details"),
            already_checked=data.get("already_checked"),
            left_for_support=data["left_for_support"],
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
    review_url = serializers.CharField(
        help_text="Link the person opens in their browser to review, edit and send the ticket."
    )
    next_step = serializers.CharField(help_text="What to tell the person now.")


class _SendFromWebAppOnly(SessionAuthenticationOnly):
    message = "Only the person can send a support ticket, from the PostHog web app."


def _claimant(request: ValidatedRequest) -> str | None:
    return request.session.session_key if hasattr(request, "session") else None


def _draft_not_found() -> Response:
    return Response({"detail": "Draft not found or expired."}, status=status.HTTP_404_NOT_FOUND)


class PostHogSupportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "posthog_support"
    # The draft reads and the claim are left out on purpose: the scope check refuses tokens on
    # unlisted actions, so only a browser session can open or send a draft.
    scope_object_write_actions = ["create_draft"]
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

    def _draft_response(self, draft: SupportTicketDraft, status_code: int = status.HTTP_200_OK) -> Response:
        data = PostHogSupportDraftSerializer(
            {
                "id": draft.id,
                "message": draft.message,
                "ticket_context": draft.ticket_context,
                "expires_at": draft.expires_at,
                "review_url": f"{settings.SITE_URL}/project/{self.team_id}/my-tickets?support_draft={draft.id}",
                "next_step": (
                    "Nothing has been sent. Show the person the message above and give them review_url. "
                    "They open it in PostHog, check and edit the ticket, and send it themselves. "
                    "Do not tell them the ticket was filed."
                ),
            }
        ).data
        return Response(data, status=status_code)

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
            draft = self._draft_store().create(message=data["message"], filing_reason=data["filing_reason"])
        except DraftCreateInProgress:
            return Response(
                {"detail": "Another draft is being saved. Try again in a few seconds."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except TooManyOpenDrafts:
            return Response(
                {"detail": "This person already has several drafts waiting for review. Ask them to send those first."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        report_user_action(
            self._user,
            "posthog support draft created",
            {
                "draft_id": draft.id,
                "filing_reason": draft.filing_reason,
                "agent_name": data.get("agent_name") or None,
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
            {"draft_id": draft_id, "filing_reason": draft.filing_reason},
            team=self.team,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
