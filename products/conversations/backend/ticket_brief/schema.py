"""The shape of the structured brief a support engineer reads before the ticket itself.

The field order is the order the brief is read in. It follows the sections of a ticket that
`products/conversations/skills/writing-posthog-support-tickets` teaches an agent to write: what
the customer wants and why, what they asked, what an assistant already answered, what they
tried, where the assistant stopped, why it needs support, then the evidence.

The serializer is the contract for both sides of the brief. It validates what the writer
produces before the brief is stored, and it types the read-only `ticket_brief` field on the
ticket API, so the OpenAPI schema and the frontend types derive from this one declaration.
"""

from rest_framework import serializers

from products.conversations.backend.models.constants import TicketBriefItemKind
from products.conversations.backend.ticket_brief.limits import (
    MAX_AFFECTED_ITEMS,
    MAX_ALREADY_ANSWERED,
    MAX_AREA,
    MAX_ASK,
    MAX_ERROR_MESSAGE,
    MAX_FACT,
    MAX_FACTS,
    MAX_ITEM_LABEL,
    MAX_PURPOSE,
    MAX_QUESTION,
    MAX_QUESTIONS,
    MAX_SCREENSHOTS,
    MAX_SUPPORT_REASON,
    MAX_TRIED,
    MAX_URL_LENGTH,
    MAX_WHERE_STOPPED,
)


class TicketBriefAffectedItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=TicketBriefItemKind.choices,
        help_text=(
            "What the link points at: ai_conversation, dashboard, experiment, feature_flag, insight, "
            "project, replay, survey, external, or other."
        ),
    )
    url = serializers.URLField(
        max_length=MAX_URL_LENGTH,
        help_text="Link the customer sent or was on, so the engineer can open it without a search.",
    )
    label = serializers.CharField(  # type: ignore[assignment]  # DRF Field.label collides with a field named label
        max_length=MAX_ITEM_LABEL,
        help_text="Short name for the link, such as the object id from its path or the page it points at.",
    )


class TicketBriefSerializer(serializers.Serializer):
    ask = serializers.CharField(
        max_length=MAX_ASK,
        help_text="What the customer needs from PostHog, in one or two sentences. The line to read first.",
    )
    # Optional because a customer often states what they want without saying why. An agent made
    # to fill the field every time invents a goal instead of reporting one, and a support
    # engineer who answers an invented purpose answers the wrong ticket.
    purpose = serializers.CharField(
        max_length=MAX_PURPOSE,
        required=False,
        allow_null=True,
        help_text=(
            "What the customer is trying to achieve behind the ask, in their own terms. "
            "Omitted when they did not say, because a guessed purpose sends the reply to the wrong problem."
        ),
    )
    area = serializers.CharField(
        max_length=MAX_AREA,
        help_text="Product area the ticket is about, such as 'Feature flags' or 'Session replay'.",
    )
    questions = serializers.ListField(
        child=serializers.CharField(max_length=MAX_QUESTION),
        max_length=MAX_QUESTIONS,
        allow_empty=True,
        help_text=(
            "Each question the customer asks, quoted in their own words from one of their messages. "
            "Empty when the customer asks nothing explicit."
        ),
    )
    already_answered = serializers.CharField(
        max_length=MAX_ALREADY_ANSWERED,
        required=False,
        allow_null=True,
        help_text=(
            "What an AI assistant already told the customer before they reached support. "
            "Omitted when no assistant worked on the problem first."
        ),
    )
    tried = serializers.ListField(
        child=serializers.CharField(max_length=MAX_FACT),
        max_length=MAX_TRIED,
        required=False,
        help_text="The steps the customer says they already took to fix or diagnose the problem.",
    )
    where_stopped = serializers.CharField(
        max_length=MAX_WHERE_STOPPED,
        required=False,
        allow_null=True,
        help_text=(
            "The first thing an AI assistant could not determine, so the engineer starts there. "
            "Omitted when no assistant worked on the problem first."
        ),
    )
    support_reason = serializers.CharField(
        max_length=MAX_SUPPORT_REASON,
        required=False,
        allow_null=True,
        help_text=(
            "What the customer cannot see or change from outside PostHog, which is why a person has to act. "
            "Omitted when the ticket does not say."
        ),
    )
    facts = serializers.ListField(
        child=serializers.CharField(max_length=MAX_FACT),
        max_length=MAX_FACTS,
        required=False,
        help_text="Details the engineer needs to act on, such as region, plan, versions, and ids. One per line.",
    )
    # A ListField rather than many=True, because the generated OpenAPI schema carries the cap
    # from a ListField and silently drops it from a nested many=True.
    affected_items = serializers.ListField(
        child=TicketBriefAffectedItemSerializer(),
        max_length=MAX_AFFECTED_ITEMS,
        required=False,
        help_text="Links to what the ticket is about: the page the customer was on, then the links they sent.",
    )
    replay_url = serializers.URLField(
        max_length=MAX_URL_LENGTH,
        required=False,
        allow_null=True,
        help_text="Replay of the session the ticket came from. Null when the ticket has no session.",
    )
    screenshot_urls = serializers.ListField(
        child=serializers.URLField(max_length=MAX_URL_LENGTH),
        max_length=MAX_SCREENSHOTS,
        required=False,
        help_text="Images the customer attached, in the order they sent them.",
    )
    error_message = serializers.CharField(
        max_length=MAX_ERROR_MESSAGE,
        required=False,
        allow_null=True,
        help_text="The error the customer reported, copied exactly. Omitted when the ticket reports no error.",
    )
