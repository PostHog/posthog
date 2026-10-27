"""The structured brief a support engineer reads before the ticket itself.

The field order is the order the brief is read in: the ask, why they want it, what they
already tried, then the evidence. The caps are deliberate. A brief is a ten-second read,
and the writer is an agent, so a field without a cap grows until it is no faster to read
than the ticket.
"""

from typing import Any

from rest_framework import serializers

from products.conversations.backend.models.constants import TicketBriefItemKind

MAX_AFFECTED_ITEMS = 5
MAX_ERROR_MESSAGE = 600
MAX_FACTS = 5
MAX_QUESTIONS = 6
MAX_SCREENSHOTS = 5
MAX_TRIED = 5
MAX_URL_LENGTH = 2000

# The fields a brief is unreadable without. Enforced in validate() rather than by `required`
# alone, because a PATCH makes the parent serializer partial and DRF propagates that into a
# nested serializer, which would skip every required field here.
#
# `purpose` is deliberately not here. A customer often states what they want without saying
# why, and an agent made to fill the field every time invents a goal instead of reporting one.
# A support engineer who answers an invented purpose answers the wrong ticket.
REQUIRED_FIELDS = ("ask", "area", "questions")


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
    purpose = serializers.CharField(
        max_length=300,
        required=False,
        allow_null=True,
        help_text=(
            "What the customer is trying to achieve behind the ask, in their own terms. "
            "Omitted when they did not say, because a guessed purpose sends the reply to the wrong problem."
        ),
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
    tried = serializers.ListField(
        child=serializers.CharField(max_length=160),
        max_length=MAX_TRIED,
        required=False,
        help_text="The steps the customer says they already took to fix or diagnose the problem.",
    )
    error_message = serializers.CharField(
        max_length=MAX_ERROR_MESSAGE,
        required=False,
        allow_null=True,
        help_text=("The error the customer reported, copied exactly. Omitted when the ticket reports no error."),
    )
    # A ListField rather than many=True, because the generated OpenAPI schema carries the cap
    # from a ListField and silently drops it from a nested many=True. Without it an agent's tool
    # schema permits six items the server then rejects.
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
        child=serializers.CharField(max_length=160),
        max_length=MAX_FACTS,
        required=False,
        help_text="Details the engineer needs to act on, such as region, plan, versions, and ids. One per line.",
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        missing = sorted(set(REQUIRED_FIELDS) - set(data))
        if missing:
            raise serializers.ValidationError(dict.fromkeys(missing, "This field is required."))
        return data
