from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.conversations.backend.temporal.ticket_patterns.recent import recent_spikes


class TicketPatternSerializer(serializers.Serializer):
    topic = serializers.CharField(help_text="Short label for the problem the tickets share.")
    summary = serializers.CharField(
        allow_blank=True, help_text="One sentence describing what the customers are hitting."
    )
    ticket_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="IDs of the tickets in this spike.",
    )
    ticket_count = serializers.IntegerField(help_text="How many tickets the spike covers.")
    requester_count = serializers.IntegerField(help_text="How many distinct customers reported it.")
    detected_at = serializers.DateTimeField(help_text="When detection reported this spike.")


class TicketPatternViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Spikes reported for this project in the last day.

    Reads a short-lived cache written when detection reports, not a table. The durable record is
    the `$conversation_ticket_pattern_detected` event, so an empty list means "nothing recent or
    nothing cached", never "this never happened".
    """

    scope_object = "INTERNAL"

    @extend_schema(
        responses={200: TicketPatternSerializer(many=True)},
        description="List the ticket spikes reported for this project in the last day, newest first.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        spikes = recent_spikes(self.team_id)
        return Response(TicketPatternSerializer(spikes, many=True).data)
