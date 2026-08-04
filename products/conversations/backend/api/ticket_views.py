import json
from typing import TYPE_CHECKING, Any, cast

from django.db.models import Exists, OuterRef

from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.api.ticket_filters import TicketViewFiltersSerializer
from products.conversations.backend.models import TicketView, TicketViewDefault, TicketViewFavorite

if TYPE_CHECKING:
    from posthog.models import User

MAX_FILTERS_SIZE_BYTES = 10_000


@extend_schema_field(TicketViewFiltersSerializer)
class TicketViewFiltersField(serializers.JSONField):
    """Validates writes against the canonical filter shape but stores and returns the raw
    dict, so unknown keys survive round-trips and legacy blobs render unchanged."""

    def to_internal_value(self, data: Any) -> dict:
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        if len(json.dumps(value)) > MAX_FILTERS_SIZE_BYTES:
            raise serializers.ValidationError("Filters payload is too large.")
        filters_serializer = TicketViewFiltersSerializer(data=value, context={"strict_writes": True})
        filters_serializer.is_valid(raise_exception=True)
        return value


class TicketViewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    filters = TicketViewFiltersField(
        required=False,
        default=dict,
        help_text="Saved ticket filter criteria: status, priority, channel, sla, aiTriageResult, assignee, "
        "tags, tagsMatch, tagsExclude, dateFrom, dateTo, sorting, and search.",
    )
    is_favorited = serializers.BooleanField(
        required=False,
        help_text="Whether the current user has favorited this view. Favorited views sort to the top of the list. Favorites are personal to each user.",
    )
    is_default = serializers.BooleanField(
        required=False,
        help_text="Whether this is the current user's default view for this project. Opening Support applies the "
        "default view's filters. Each user has at most one default per project, so setting a new default replaces "
        "the previous one. Defaults are personal to each user.",
    )

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
            "is_default",
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

    def _set_default(self, instance: TicketView, is_default: bool) -> None:
        user = self.context["request"].user
        if is_default:
            # (team, user) is unique, so promoting a view demotes the previous default in the same
            # upsert — no window where the user has two defaults or none.
            TicketViewDefault.objects.update_or_create(
                team_id=instance.team_id, user=user, defaults={"ticket_view": instance}
            )
        else:
            # Filtered by ticket_view so clearing view A can never drop a default pointing at view B.
            TicketViewDefault.objects.filter(team_id=instance.team_id, user=user, ticket_view=instance).delete()
        # Read back by perform_create/perform_update for tracking; the flag never reaches validated_data.
        instance._default_changed_to = is_default

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> TicketView:
        is_favorited = validated_data.pop("is_favorited", False)
        is_default = validated_data.pop("is_default", False)
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        instance = super().create(validated_data)
        if is_favorited:
            self._set_favorited(instance, True)
        instance.is_favorited = bool(is_favorited)
        if is_default:
            self._set_default(instance, True)
        instance.is_default = bool(is_default)
        return instance

    def update(self, instance: TicketView, validated_data: dict[str, Any]) -> TicketView:
        is_favorited = validated_data.pop("is_favorited", None)
        is_default = validated_data.pop("is_default", None)
        instance = super().update(instance, validated_data)
        if is_favorited is not None:
            self._set_favorited(instance, is_favorited)
            instance.is_favorited = is_favorited
        if is_default is not None:
            self._set_default(instance, is_default)
            instance.is_default = is_default
        return instance


class DefaultTicketViewSerializer(serializers.Serializer):
    """Wraps the view so the endpoint has a stable response shape when no default is set."""

    default_view = TicketViewSerializer(
        allow_null=True,
        help_text="The requesting user's default view for this project, or null if they haven't set one.",
    )


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
    scope_object_read_actions = ["list", "retrieve", "default"]
    # PATCH only: full PUT would reset omitted fields (filters defaults to {}), clearing saved criteria
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: Any) -> Any:
        queryset = queryset.filter(team_id=self.team_id)
        queryset = queryset.select_related("created_by")
        user = cast("User", self.request.user)
        # Personal favorites float to the top, for the requesting user only.
        favorited_by_user = TicketViewFavorite.objects.filter(ticket_view_id=OuterRef("pk"), user=user)
        default_for_user = TicketViewDefault.objects.filter(ticket_view_id=OuterRef("pk"), user=user)
        # The default deliberately does not float above favorites: it's marked in the UI instead, so
        # setting one doesn't reshuffle the list for a preference most users never touch.
        queryset = queryset.annotate(
            is_favorited=Exists(favorited_by_user), is_default=Exists(default_for_user)
        ).order_by("-is_favorited", "-created_at")
        return queryset

    @extend_schema(responses={200: DefaultTicketViewSerializer})
    @action(detail=False, methods=["get"])
    def default(self, request: Request, **kwargs: Any) -> Response:
        """The requesting user's default view, in one request so the ticket list can be fetched with the
        right filters on first load. Routed before the short_id detail route, and short_ids are 8
        characters, so "default" can never shadow a real view."""
        user = cast("User", request.user)
        row = (
            TicketViewDefault.objects.filter(team_id=self.team_id, user=user)
            .select_related("ticket_view", "ticket_view__created_by")
            .first()
        )
        view = row.ticket_view if row else None
        if view is not None:
            view.is_default = True
            view.is_favorited = TicketViewFavorite.objects.filter(ticket_view=view, user=user).exists()
        serializer = DefaultTicketViewSerializer({"default_view": view}, context=self.get_serializer_context())
        return Response(serializer.data)

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

    def _track_default_change(self, instance: TicketView) -> None:
        changed_to = getattr(instance, "_default_changed_to", None)
        if changed_to is not None:
            self._track("ticket view default set" if changed_to else "ticket view default cleared", instance)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        instance = serializer.save()
        self._track("ticket view created", instance)
        self._track_default_change(instance)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        instance = serializer.save()
        self._track("ticket view updated", instance)
        self._track_default_change(instance)

    def perform_destroy(self, instance: TicketView) -> None:
        self._track("ticket view deleted", instance)
        super().perform_destroy(instance)
