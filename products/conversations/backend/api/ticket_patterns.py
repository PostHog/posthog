from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.db import transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.conversations.backend.models import (
    Ticket,
    TicketPattern,
    TicketPatternEvidence,
    TicketPatternStatus,
    TicketTopicBaseline,
)
from products.conversations.backend.models.constants import Priority

if TYPE_CHECKING:
    from posthog.models import User

MAX_DISMISS_REASON_LENGTH = 500
EVIDENCE_PREVIEW_LIMIT = 10


class PatternEvidenceTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ["id", "ticket_number", "channel_source", "email_subject", "status", "created_at"]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Ticket UUID."},
            "ticket_number": {"help_text": "Team-scoped ticket number shown as #N in the inbox."},
            "channel_source": {"help_text": "Channel the ticket arrived on."},
            "email_subject": {"help_text": "Subject line for email tickets, empty for other channels."},
            "status": {"help_text": "Current ticket status."},
            "created_at": {"help_text": "When the ticket was opened."},
        }


class TicketPatternSerializer(serializers.ModelSerializer):
    resolved_by = UserBasicSerializer(
        read_only=True, allow_null=True, help_text="Who confirmed or dismissed the pattern."
    )
    owner = UserBasicSerializer(read_only=True, allow_null=True, help_text="Who took ownership when confirming.")
    tickets = serializers.SerializerMethodField(
        help_text=f"Up to {EVIDENCE_PREVIEW_LIMIT} of the tickets behind this pattern, newest first, "
        "limited to tickets the requesting user can open."
    )

    class Meta:
        model = TicketPattern
        fields = [
            "id",
            "topic",
            "source",
            "title",
            "summary",
            "status",
            "severity",
            "ticket_count",
            "requester_count",
            "peak_ticket_count",
            "first_ticket_at",
            "opened_at",
            "last_seen_at",
            "resolved_at",
            "resolved_by",
            "owner",
            "evidence",
            "tickets",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Pattern UUID."},
            "topic": {"help_text": "The normalized term or term pair the tickets share."},
            "source": {"help_text": "How the tickets were grouped: term match or embeddings."},
            "title": {"help_text": "Short human-readable name for the pattern."},
            "summary": {"help_text": "One or two sentences on what the tickets report, when available."},
            "status": {"help_text": "open until a person confirms or dismisses it; resolved when it goes quiet."},
            "severity": {"help_text": "Priority a person assigned on confirm, medium by default."},
            "ticket_count": {"help_text": "Tickets matched in the most recent detection window."},
            "requester_count": {"help_text": "Distinct customers among those tickets."},
            "peak_ticket_count": {"help_text": "Highest ticket_count seen while the pattern was open."},
            "first_ticket_at": {"help_text": "When the earliest matching ticket arrived."},
            "opened_at": {"help_text": "When detection first opened the pattern."},
            "last_seen_at": {"help_text": "When detection last saw the topic still firing."},
            "resolved_at": {"help_text": "When the pattern was confirmed, dismissed, or auto-resolved."},
            "evidence": {"help_text": "Free-form context: correlation results, dismiss reason, auto_resolved flag."},
        }

    @extend_schema_field(PatternEvidenceTicketSerializer(many=True))
    def get_tickets(self, pattern: TicketPattern) -> list[dict[str, Any]]:
        visible = self.context.get("visible_ticket_ids")
        if visible is None:
            return []
        ticket_ids = list(
            TicketPatternEvidence.objects.for_team(pattern.team_id)
            .filter(pattern=pattern, ticket_id__in=visible)
            .order_by("-added_at")
            .values_list("ticket_id", flat=True)[:EVIDENCE_PREVIEW_LIMIT]
        )
        tickets = {t.id: t for t in Ticket.objects.filter(team_id=pattern.team_id, id__in=ticket_ids)}
        return list(PatternEvidenceTicketSerializer([tickets[i] for i in ticket_ids if i in tickets], many=True).data)


class ConfirmPatternSerializer(serializers.Serializer):
    severity = serializers.ChoiceField(
        choices=Priority.choices, required=False, help_text="Priority to record on the pattern. Defaults to medium."
    )
    take_ownership = serializers.BooleanField(default=True, help_text="Set the requesting user as the pattern's owner.")


class DismissPatternSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_DISMISS_REASON_LENGTH,
        help_text="Optional note on why this is not an incident. Stored on the pattern for later review.",
    )


class PatternFilterSerializer(serializers.Serializer):
    """Validates the list query parameters, so a bad value answers 400 rather than reaching the ORM."""

    status = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Comma-separated statuses to include: open, confirmed, dismissed, resolved.",
    )
    ticket_id = serializers.UUIDField(required=False, help_text="Only patterns this ticket is evidence for.")

    def validate_status(self, value: str) -> list[str]:
        statuses = [s for s in value.split(",") if s]
        unknown = [s for s in statuses if s not in TicketPatternStatus.values]
        if unknown:
            raise serializers.ValidationError(f"Unknown status: {', '.join(unknown)}.")
        return statuses


class TicketPatternViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Clusters of tickets from distinct customers about one topic, found by the pattern detector.

    Read-only apart from the two state transitions, which are POST actions rather than PATCH so a
    client cannot set a pattern back to open, and so the baseline feedback that makes the detector
    learn happens in the same request.
    """

    # "ticket" (not "conversation"): the conversation scope also authorizes AI conversation
    # endpoints, which support patterns have no business granting access to
    scope_object = "ticket"
    serializer_class = TicketPatternSerializer
    queryset = TicketPattern.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # Environment-scoped model: filter on the literal team id, never the canonical one.
        queryset = TicketPattern.objects.for_team(self.team_id).select_related("resolved_by", "owner")
        filters = PatternFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        statuses = filters.validated_data.get("status")
        if statuses:
            queryset = queryset.filter(status__in=statuses)
        ticket_id = filters.validated_data.get("ticket_id")
        if ticket_id:
            queryset = queryset.filter(evidence_tickets__ticket_id=ticket_id)
        return queryset.order_by("-last_seen_at")

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        if self.action in ("list", "retrieve", "confirm", "dismiss"):
            context["visible_ticket_ids"] = self._visible_ticket_ids()
        return context

    def _visible_ticket_ids(self) -> set[Any]:
        # Ticket-level access control exists; a pattern must not leak a title the user cannot open.
        tickets = Ticket.objects.filter(team_id=self.team_id)
        access_control = cast(UserAccessControl, self.user_access_control)
        return set(access_control.filter_queryset_by_access_level(tickets).values_list("id", flat=True))

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                description="Comma-separated statuses to include: open, confirmed, dismissed, resolved.",
            ),
            OpenApiParameter("ticket_id", str, description="Only patterns this ticket is evidence for."),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def _transition(self, pattern: TicketPattern, new_status: str) -> None:
        if pattern.status != TicketPatternStatus.OPEN:
            raise serializers.ValidationError({"status": f"Only an open pattern can be {new_status}."})
        pattern.status = new_status
        pattern.resolved_at = timezone.now()
        pattern.resolved_by = cast("User", self.request.user)

    def _record_feedback(self, pattern: TicketPattern, field: str) -> None:
        # The detector raises the bar for a dismissed topic and lowers it for a confirmed one.
        TicketTopicBaseline.objects.for_team(self.team_id).filter(topic=pattern.topic).update(**{field: F(field) + 1})

    def _track(self, event: str, pattern: TicketPattern) -> None:
        report_user_action(
            self.request.user,
            event,
            {
                "pattern_id": str(pattern.id),
                "source": pattern.source,
                "severity": pattern.severity,
                "ticket_count": pattern.ticket_count,
                "requester_count": pattern.requester_count,
                "seconds_open": int((pattern.resolved_at - pattern.opened_at).total_seconds())
                if pattern.resolved_at
                else None,
            },
            team=self.team,
            request=self.request,
        )

    @extend_schema(request=ConfirmPatternSerializer, responses={200: TicketPatternSerializer})
    @action(methods=["POST"], detail=True)
    def confirm(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = ConfirmPatternSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        pattern = self.get_object()
        with transaction.atomic():
            self._transition(pattern, TicketPatternStatus.CONFIRMED)
            pattern.severity = body.validated_data.get("severity", pattern.severity)
            if body.validated_data["take_ownership"]:
                pattern.owner = cast("User", request.user)
            pattern.save(update_fields=["status", "resolved_at", "resolved_by", "severity", "owner", "updated_at"])
            self._record_feedback(pattern, "confirm_count")
        self._track("support pattern confirmed", pattern)
        return Response(self.get_serializer(pattern).data, status=status.HTTP_200_OK)

    @extend_schema(request=DismissPatternSerializer, responses={200: TicketPatternSerializer})
    @action(methods=["POST"], detail=True)
    def dismiss(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = DismissPatternSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        pattern = self.get_object()
        with transaction.atomic():
            self._transition(pattern, TicketPatternStatus.DISMISSED)
            reason = body.validated_data.get("reason", "").strip()
            if reason:
                pattern.evidence = {**pattern.evidence, "dismiss_reason": reason}
            pattern.save(update_fields=["status", "resolved_at", "resolved_by", "evidence", "updated_at"])
            self._record_feedback(pattern, "dismiss_count")
        self._track("support pattern dismissed", pattern)
        return Response(self.get_serializer(pattern).data, status=status.HTTP_200_OK)
