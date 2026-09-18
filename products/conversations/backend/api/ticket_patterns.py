from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.conversations.backend.temporal.ticket_patterns.recent import dismiss_spike, recent_spikes


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
    dismissed_by = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Name of the teammate who dismissed this spike for the project, if anyone has.",
    )
    dismissed_at = serializers.DateTimeField(required=False, allow_null=True, help_text="When the spike was dismissed.")


class TicketPatternDismissSerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text="Identity of the spike to dismiss, as `topic:detected_at` from the list response."
    )


class TicketPatternViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Spikes reported for this project in the last day.

    Reads a short-lived cache written when detection reports, not a table. The durable record is
    the `$conversation_ticket_pattern_detected` event, so an empty list means "nothing recent or
    nothing cached", never "this never happened".
    """

    scope_object = "INTERNAL"
    queryset = None
    # The list is capped at MAX_RECENT_SPIKES and returned whole, so a page envelope would
    # describe a response this view never sends.
    pagination_class = None

    def get_serializer_class(self) -> type[serializers.Serializer]:
        # Per action, so the generated client asks for a key to dismiss rather than a whole spike.
        if self.action == "dismiss":
            return TicketPatternDismissSerializer
        return TicketPatternSerializer

    @extend_schema(
        responses={200: TicketPatternSerializer(many=True)},
        description="List the ticket spikes reported for this project in the last day, newest first.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        # Reported spikes outlive the setting by up to a day, so a team that switched detection
        # off must stop seeing them rather than wait for the cache to expire.
        settings_dict = self.team.conversations_settings or {}
        if not settings_dict.get("ticket_patterns_enabled"):
            return Response([])
        spikes = recent_spikes(self.team_id)
        return Response(TicketPatternSerializer(spikes, many=True).data)

    @action(detail=False, methods=["POST"])
    @validated_request(
        TicketPatternDismissSerializer,
        responses={204: None},
        description="Dismiss one spike for everyone in the project, so the inbox banner stops showing it.",
    )
    def dismiss(self, request: ValidatedRequest, **kwargs) -> Response:
        user = request.user
        name = getattr(user, "first_name", "") or getattr(user, "email", "") or "a teammate"
        if not dismiss_spike(self.team_id, request.validated_data["key"], name):
            return Response({"detail": "No such spike."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
