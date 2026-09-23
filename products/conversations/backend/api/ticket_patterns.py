from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.ticket_patterns.eligibility import is_master_flag_enabled
from products.conversations.backend.temporal.ticket_patterns.recent import dismiss_spike, recent_spikes, spike_key


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


class TicketPatternDismissErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the spike could not be dismissed.")


class TicketPatternViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    """Spikes reported for this project in the last day.

    Reads a short-lived cache written when detection reports, not a table. The durable record is
    the `$conversation_ticket_pattern_detected` event, so an empty list means "nothing recent or
    nothing cached", never "this never happened".

    A spike is made of ticket text, so it is scoped as ticket data: a user sees a spike only when
    they can open every ticket in it, and never learns that the others exist.
    """

    scope_object = "ticket"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["dismiss"]
    queryset = Ticket.objects.all()
    # The list is capped at MAX_RECENT_SPIKES and returned whole, so a page envelope would
    # describe a response this view never sends.
    pagination_class = None

    def get_serializer_class(self) -> type[serializers.Serializer]:
        # Per action, so the generated client asks for a key to dismiss rather than a whole spike.
        if self.action == "dismiss":
            return TicketPatternDismissSerializer
        return TicketPatternSerializer

    def _detection_is_live(self) -> bool:
        """Whether this project should be seeing spikes at all.

        Reported spikes outlive both switches by up to a day, so a team that turned detection off,
        or one the rollout flag was pulled from, must stop seeing them rather than wait out the
        cache.
        """
        if not (self.team.conversations_settings or {}).get("ticket_patterns_enabled"):
            return False
        return is_master_flag_enabled(self.team)

    def _visible_spikes(self) -> list[dict]:
        """The cached spikes this user may see, whole.

        A spike is all-or-nothing rather than narrowed to the readable tickets, because its topic
        and summary are written from every ticket in the cluster. Trimming the id list would still
        hand over text derived from tickets the user cannot open, and there is no way to redact
        that without asking the model again. Whole-spike visibility also makes the project-wide
        dismissal defensible: anyone who can dismiss a spike can already read all of it.
        """
        spikes = recent_spikes(self.team_id)
        if not spikes:
            return []

        # Only well-formed ids reach the query: this list is a cache blob, and an id the Ticket
        # model cannot parse raises rather than returning nothing, which would fail the inbox
        # scene the banner sits on instead of just dropping the banner.
        parsed: dict[int, list[str]] = {}
        for index, spike in enumerate(spikes):
            ids = []
            for ticket_id in spike.get("ticket_ids", []):
                try:
                    ids.append(str(UUID(str(ticket_id))))
                except (ValueError, AttributeError, TypeError):
                    # A spike is only shown whole, so an unparseable id means it cannot be shown.
                    ids = []
                    break
            if ids:
                parsed[index] = ids

        every_id = {ticket_id for ids in parsed.values() for ticket_id in ids}
        if not every_id:
            return []

        queryset = Ticket.objects.filter(team_id=self.team_id, id__in=every_id)
        uac = self.user_access_control
        if bool(uac.blocked_resource_ids_by_scope.get("ticket")) or not uac.has_resource_access("ticket"):
            queryset = uac.filter_queryset_by_access_level(queryset)
        readable = {str(ticket_id) for ticket_id in queryset.values_list("id", flat=True)}

        return [spikes[index] for index, ids in parsed.items() if readable.issuperset(ids)]

    @extend_schema(
        responses={200: TicketPatternSerializer(many=True)},
        description="List the ticket spikes reported for this project in the last day, newest first.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        if not self._detection_is_live():
            return Response([])
        return Response(TicketPatternSerializer(self._visible_spikes(), many=True).data)

    # @validated_request must sit OUTSIDE @action: DRF's @action resets func.kwargs, wiping any
    # schema annotation applied earlier, so the generated client would describe the wrong response.
    @validated_request(
        TicketPatternDismissSerializer,
        responses={204: None, 404: OpenApiResponse(response=TicketPatternDismissErrorSerializer)},
        description="Dismiss one spike for everyone in the project, so the inbox banner stops showing it.",
    )
    @action(detail=False, methods=["POST"])
    def dismiss(self, request: ValidatedRequest, **kwargs) -> Response:
        key = request.validated_data["key"]
        # Dismissing is project-wide, so it is gated on the same visibility as reading: a user who
        # cannot see the spike cannot hide it from the teammates who can.
        if not self._detection_is_live() or not any(spike_key(s) == key for s in self._visible_spikes()):
            return Response({"detail": "No such spike."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        name = getattr(user, "first_name", "") or getattr(user, "email", "") or "a teammate"
        if not dismiss_spike(self.team_id, key, name):
            return Response({"detail": "No such spike."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
