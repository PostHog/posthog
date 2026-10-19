"""The structured brief a support engineer reads before the ticket itself.

The caps are deliberate. A brief is a ten-second read, and the writer is an agent,
so a field without a cap grows until it is no faster to read than the ticket.
"""

from rest_framework import serializers

from products.conversations.backend.models.constants import TicketBriefItemKind

MAX_AFFECTED_ITEMS = 5
MAX_FACTS = 5
MAX_QUESTIONS = 6
MAX_SCREENSHOTS = 5
MAX_TRIED = 5
MAX_URL_LENGTH = 2000


class TicketBriefAffectedItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=TicketBriefItemKind.choices,
        help_text="What the customer is asking about: dashboard, experiment, feature_flag, insight, project, replay, survey, or other.",
    )
    url = serializers.URLField(
        max_length=MAX_URL_LENGTH,
        help_text="Link to the item in PostHog, so the engineer can open it without a search.",
    )
    label = serializers.CharField(
        max_length=120,
        help_text="Name of the item as the customer would recognize it.",
    )


class TicketBriefSerializer(serializers.Serializer):
    ask = serializers.CharField(
        max_length=400,
        help_text="What the customer needs from PostHog, in one or two sentences. The line to read first.",
    )
    area = serializers.CharField(
        max_length=80,
        help_text="Product area the ticket is about, such as 'Feature flags' or 'Session replay'.",
    )
    questions = serializers.ListField(
        child=serializers.CharField(max_length=200),
        max_length=MAX_QUESTIONS,
        allow_empty=True,
        help_text="Each question the customer asks, as one short line. Empty when the customer asks nothing explicit.",
    )
    affected_items = TicketBriefAffectedItemSerializer(
        many=True,
        required=False,
        max_length=MAX_AFFECTED_ITEMS,
        help_text="The PostHog items the ticket is about, with a link to each one.",
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
    facts = serializers.ListField(
        child=serializers.CharField(max_length=160),
        max_length=MAX_FACTS,
        required=False,
        help_text="Details the engineer needs to act on, such as region, plan, versions, and ids. One per line.",
    )
    tried = serializers.ListField(
        child=serializers.CharField(max_length=160),
        max_length=MAX_TRIED,
        required=False,
        help_text="What the customer says they already did to fix or diagnose the problem.",
    )
