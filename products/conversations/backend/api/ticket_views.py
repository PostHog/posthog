import json
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.models import TicketView

MAX_FILTERS_SIZE_BYTES = 10_000


class TicketViewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    filters = serializers.DictField(
        required=False,
        default=dict,
        help_text="Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys.",
    )

    def validate_filters(self, value: dict) -> dict:
        if len(json.dumps(value)) > MAX_FILTERS_SIZE_BYTES:
            raise serializers.ValidationError("Filters payload is too large.")
        return value

    class Meta:
        model = TicketView
        fields = [
            "id",
            "short_id",
            "name",
            "filters",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "created_at",
            "created_by",
        ]

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> TicketView:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


@extend_schema(tags=["conversations"])
class TicketViewViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "conversation"
    queryset = TicketView.objects.all().order_by("-created_at")
    serializer_class = TicketViewSerializer
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset: Any) -> Any:
        queryset = queryset.filter(team_id=self.team_id)
        queryset = queryset.select_related("created_by")
        return queryset

    def _track(self, event: str, instance: TicketView) -> None:
        report_user_action(
            self.request.user,
            event,
            {
                "id": str(instance.id),
                "short_id": instance.short_id,
                "name": instance.name,
                "has_filters": bool(instance.filters),
            },
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        self._track("ticket view created", serializer.save())

    def perform_destroy(self, instance: TicketView) -> None:
        self._track("ticket view deleted", instance)
        super().perform_destroy(instance)
