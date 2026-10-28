"""The shape of the structured brief a support engineer reads before the ticket itself.

The field order is the order the brief is read in: the ask, why they want it, what they
already tried, then the evidence.

The serializer is the contract for both sides of the brief. It validates what the writer
produces before the brief is stored, and it types the read-only `ticket_brief` field on the
ticket API, so the OpenAPI schema and the frontend types derive from this one declaration.
"""

from rest_framework import serializers

from products.conversations.backend.models.constants import TicketBriefItemKind
from products.conversations.backend.ticket_brief.limits import (
    MAX_AFFECTED_ITEMS,
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
    MAX_TRIED,
    MAX_URL_LENGTH,
)


class TicketBriefAffectedItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=TicketBriefItemKind.choices,
        help_text="What the customer is asking about: dashboard, experiment, feature_flag, insight, project, replay, survey, external, or other.",
    )
    url = serializers.URLField(
        max_length=MAX_URL_LENGTH,
        help_text="Link to the item in PostHog, so the engineer can open it without a search.",
    )
    label = serializers.CharField(  # type: ignore[assignment]  # DRF Field.label collides with a field named label
        max_length=MAX_ITEM_LABEL,
        help_text="Name of the item as the customer would recognize it.",
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
        help_text="Each question the customer asks, as one short line. Empty when the customer asks nothing explicit.",
    )
    tried = serializers.ListField(
        child=serializers.CharField(max_length=MAX_FACT),
        max_length=MAX_TRIED,
        required=False,
        help_text="The steps the customer says they already took to fix or diagnose the problem.",
    )
    error_message = serializers.CharField(
        max_length=MAX_ERROR_MESSAGE,
        required=False,
        allow_null=True,
        help_text="The error the customer reported, copied exactly. Omitted when the ticket reports no error.",
    )
    # A ListField rather than many=True, because the generated OpenAPI schema carries the cap
    # from a ListField and silently drops it from a nested many=True.
    affected_items = serializers.ListField(
        child=TicketBriefAffectedItemSerializer(),
        max_length=MAX_AFFECTED_ITEMS,
        required=False,
        help_text="The items the ticket is about, with a link to each one.",
    )
    screenshot_urls = serializers.ListField(
        child=serializers.URLField(max_length=MAX_URL_LENGTH),
        max_length=MAX_SCREENSHOTS,
        required=False,
        help_text="Images the customer attached, in the order they sent them.",
    )
    replay_url = serializers.URLField(
        max_length=MAX_URL_LENGTH,
        required=False,
        allow_null=True,
        help_text="Replay of the session the ticket came from. Null when the ticket has no session.",
    )
    facts = serializers.ListField(
        child=serializers.CharField(max_length=MAX_FACT),
        max_length=MAX_FACTS,
        required=False,
        help_text="Details the engineer needs to act on, such as region, plan, versions, and ids. One per line.",
    )
