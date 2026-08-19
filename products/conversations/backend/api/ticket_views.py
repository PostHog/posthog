import json
from typing import TYPE_CHECKING, Any, cast

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.file_system.file_system import split_path

from products.conversations.backend.api.ticket_filters import TicketViewFiltersSerializer
from products.conversations.backend.api.ticket_view_folders import (
    MAX_FOLDER_LENGTH,
    is_folder_under,
    normalize_folder,
    reparent_folder,
)
from products.conversations.backend.models import TicketView, TicketViewFavorite

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
    folder = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_FOLDER_LENGTH,
        help_text='Team-shared folder this view sits in, for example "Escalations/EU". An empty string '
        'means the view sits at the top level. Nest folders with "/"; a literal slash inside a folder '
        'name is escaped as "\\/". Folders are shared with the whole team and exist only while at '
        "least one view is in them.",
    )

    class Meta:
        model = TicketView
        fields = [
            "id",
            "short_id",
            "name",
            "filters",
            "folder",
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

    def validate_folder(self, value: str) -> str:
        return normalize_folder(value)

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


class MoveFolderRequestSerializer(serializers.Serializer):
    from_folder = serializers.CharField(
        max_length=MAX_FOLDER_LENGTH,
        help_text='Folder to move, for example "Escalations". Required, and the top level cannot be moved.',
    )
    to_folder = serializers.CharField(
        allow_blank=True,
        max_length=MAX_FOLDER_LENGTH,
        help_text='Where the folder should end up, for example "Ops/Escalations". An empty string moves '
        "its views to the top level, which removes the folder.",
    )

    def validate_from_folder(self, value: str) -> str:
        normalized = normalize_folder(value)
        if not normalized:
            raise serializers.ValidationError("Choose a folder to move.")
        return normalized

    def validate_to_folder(self, value: str) -> str:
        return normalize_folder(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        from_folder, to_folder = attrs["from_folder"], attrs["to_folder"]
        if from_folder == to_folder:
            raise serializers.ValidationError("That folder is already in this location. Pick a different destination.")
        if is_folder_under(to_folder, from_folder):
            raise serializers.ValidationError("A folder can't move inside itself. Pick a destination outside it.")
        return attrs


class MoveFolderResponseSerializer(serializers.Serializer):
    moved = serializers.IntegerField(help_text="How many views changed folder.")
    short_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="short_id of every view that moved.",
    )
    to_folder = serializers.CharField(
        allow_blank=True,
        help_text="Normalized destination the views now sit in.",
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
                "folder_depth": len(split_path(instance.folder)),
            },
            team=self.team,
            request=self.request,
        )

    @validated_request(
        request_serializer=MoveFolderRequestSerializer,
        responses={200: OpenApiResponse(response=MoveFolderResponseSerializer)},
        summary="Move or rename a folder of saved views",
        description="Move a folder and everything nested under it to a new location. Renaming a folder is "
        "the same operation with a new final path segment. Folders are not stored as rows, so this rewrites "
        "the folder path on every view at or below the given folder.",
    )
    @action(detail=False, methods=["POST"], pagination_class=None)
    def move_folder(self, request, *args: Any, **kwargs: Any) -> Response:
        from_folder: str = request.validated_data["from_folder"]
        to_folder: str = request.validated_data["to_folder"]

        with transaction.atomic():
            # team_id is the tenant boundary for this write. safely_get_queryset can't be reused
            # here because its is_favorited annotation and select_related don't survive bulk_update.
            # The trailing "/" is a whole-segment boundary: a folder whose name really contains a
            # slash is stored escaped ("Escalations\/EU"), so a sibling sharing a name prefix
            # cannot match.
            rows = list(
                TicketView.objects.filter(team_id=self.team_id)
                .filter(Q(folder=from_folder) | Q(folder__startswith=f"{from_folder}/"))
                .select_for_update(of=("self",))
            )
            if not rows:
                raise NotFound("That folder no longer exists. Refresh to see the current folders.")

            # Resolving every destination up front means an over-deep result rejects the whole
            # move rather than half-applying it.
            new_folders = [normalize_folder(reparent_folder(row.folder, from_folder, to_folder)) for row in rows]

            moved_at = timezone.now()
            for row, new_folder in zip(rows, new_folders):
                row.folder = new_folder
                row.updated_at = moved_at
            TicketView.objects.bulk_update(rows, ["folder", "updated_at"])

        # Depths rather than paths: folder names describe how a team organizes its work.
        report_user_action(
            request.user,
            "ticket view folder moved",
            {
                "count": len(rows),
                "from_depth": len(split_path(from_folder)),
                "to_depth": len(split_path(to_folder)),
            },
            team=self.team,
            request=request,
        )
        return Response({"moved": len(rows), "short_ids": [row.short_id for row in rows], "to_folder": to_folder})

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        self._track("ticket view created", serializer.save())

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._track("ticket view updated", serializer.save())

    def perform_destroy(self, instance: TicketView) -> None:
        self._track("ticket view deleted", instance)
        super().perform_destroy(instance)
