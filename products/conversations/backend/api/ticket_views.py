import json
from typing import TYPE_CHECKING, Any, cast

from django.db.models import Exists, OuterRef

from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.models import TicketView, TicketViewFavorite

if TYPE_CHECKING:
    from posthog.models import User

MAX_FILTERS_SIZE_BYTES = 10_000


class TicketViewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    filters = serializers.DictField(
        required=False,
        default=dict,
        help_text="Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys.",
    )
    is_favorited = serializers.BooleanField(
        required=False,
        help_text="Whether the current user has favorited this view. Favorited views sort to the top of the list. Favorites are personal to each user.",
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
            "is_favorited",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "created_at",
            "created_by",
        ]

    def _set_favorited(self, instance: TicketView, favorited: bool) -> None:
        user = self.context["request"].user
        if favorited:
            TicketViewFavorite.objects.get_or_create(team=instance.team, ticket_view=instance, user=user)
        else:
            TicketViewFavorite.objects.filter(team=instance.team, ticket_view=instance, user=user).delete()

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> TicketView:
        is_favorited = validated_data.pop("is_favorited", False)
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        instance = super().create(validated_data)
        if is_favorited:
            self._set_favorited(instance, True)
        instance.is_favorited = bool(is_favorited)
        return instance

    def update(self, instance: TicketView, validated_data: dict[str, Any]) -> TicketView:
        is_favorited = validated_data.pop("is_favorited", None)
        instance = super().update(instance, validated_data)
        if is_favorited is not None:
            self._set_favorited(instance, is_favorited)
            instance.is_favorited = is_favorited
        return instance


class TicketViewViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    # "ticket" (not "conversation"): the conversation scope also authorizes AI conversation
    # endpoints, which saved ticket views have no business granting access to
    scope_object = "ticket"
    queryset = TicketView.objects.all().order_by("-created_at")
    serializer_class = TicketViewSerializer
    lookup_field = "short_id"
    # PATCH only: full PUT would reset omitted fields (filters defaults to {}), clearing saved criteria
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: Any) -> Any:
        queryset = queryset.filter(team_id=self.team_id)
        queryset = queryset.select_related("created_by")
        # Personal favorites float to the top, for the requesting user only.
        favorited_by_user = TicketViewFavorite.objects.filter(
            ticket_view_id=OuterRef("pk"), user=cast("User", self.request.user)
        )
        queryset = queryset.annotate(is_favorited=Exists(favorited_by_user)).order_by("-is_favorited", "-created_at")
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

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._track("ticket view updated", serializer.save())

    def perform_destroy(self, instance: TicketView) -> None:
        self._track("ticket view deleted", instance)
        super().perform_destroy(instance)
