import json
from collections.abc import Mapping
from typing import Any, Literal, TypedDict, cast

from django.db import models, transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.helpers.trigram_search import MAX_SEARCH_LENGTH
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.dashboards.backend.feature_flags import dashboard_saved_views_enabled
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_saved_view import DashboardSavedView

SAVED_VIEW_FILTER_KEYS = {"search", "createdBy", "pinned", "shared", "tags", "folder"}
MAX_SAVED_VIEW_FILTER_BYTES = 16 * 1024
MAX_SAVED_VIEW_FILTER_STRING_LENGTH = MAX_SEARCH_LENGTH
MAX_SAVED_VIEW_FOLDER_LENGTH = 4000
MAX_SAVED_VIEW_TAGS = 50
MAX_SAVED_VIEW_TAG_LENGTH = 100
MAX_SAVED_VIEW_CREATORS = 100
MAX_TEAM_SAVED_VIEWS = 200
MAX_PERSONAL_SAVED_VIEWS = 50


class DashboardSavedViewFilters(TypedDict, total=False):
    search: str
    createdBy: list[int] | Literal["All users"]
    pinned: bool
    shared: bool
    tags: list[str]
    folder: str | None


def saved_view_filter_properties(filters: Mapping[str, object]) -> dict[str, bool | int]:
    tags = filters.get("tags", [])
    tag_count = len(tags) if isinstance(tags, list) else 0
    has_search = bool(filters.get("search"))
    has_folder = filters.get("folder") is not None
    has_tags = tag_count > 0
    created_by = filters.get("createdBy")
    has_creator = isinstance(created_by, list) and len(created_by) > 0
    is_pinned = bool(filters.get("pinned"))
    is_shared = bool(filters.get("shared"))

    return {
        "has_search_filter": has_search,
        "has_folder_filter": has_folder,
        "has_tag_filter": has_tags,
        "tag_count": tag_count,
        "has_creator_filter": has_creator,
        "is_pinned": is_pinned,
        "is_shared": is_shared,
        "active_filter_count": sum([has_search, has_folder, has_tags, has_creator, is_pinned, is_shared]),
    }


def has_saved_view_filters(filters: Mapping[str, object]) -> bool:
    return any(
        saved_view_filter_properties(filters)[property]
        for property in [
            "has_search_filter",
            "has_folder_filter",
            "has_tag_filter",
            "has_creator_filter",
            "is_pinned",
            "is_shared",
        ]
    )


def saved_view_creator_properties(*, team_id: int, user_id: int) -> dict[str, int]:
    return {
        "saved_views_created_by_user_count": DashboardSavedView.objects.for_team(team_id)
        .filter(created_by_id=user_id)
        .count(),
        "dashboards_created_by_user_count": Dashboard.objects.filter(team_id=team_id, created_by_id=user_id).count(),
    }


@extend_schema_field(
    {
        "oneOf": [
            {"type": "array", "items": {"type": "integer"}, "maxItems": MAX_SAVED_VIEW_CREATORS},
            {"type": "string", "enum": ["All users"]},
        ]
    }
)
class DashboardSavedViewCreatorsField(serializers.Field):
    def to_internal_value(self, data: object) -> list[int] | Literal["All users"]:
        if data == "All users":
            return "All users"
        if not isinstance(data, list) or any(type(creator) is not int for creator in data):
            raise serializers.ValidationError("Creators must be a list of user IDs.")
        if len(data) > MAX_SAVED_VIEW_CREATORS:
            raise serializers.ValidationError("You can select up to 100 creators.")
        creator_ids = set(cast(list[int], data))
        team = cast(Team, self.root.context["get_team"]())
        canonical_team = team.parent_team or team
        member_ids = set(
            canonical_team.organization.members.filter(pk__in=creator_ids, is_active=True).values_list("pk", flat=True)
        )
        if creator_ids != member_ids:
            raise serializers.ValidationError("Creators must be active members of this project.")
        return cast(list[int], data)

    def to_representation(self, value: object) -> object:
        return value


class DashboardSavedViewFiltersSerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_SAVED_VIEW_FILTER_STRING_LENGTH,
        trim_whitespace=False,
        error_messages={"max_length": "Search must be 200 characters or fewer."},
    )
    createdBy = DashboardSavedViewCreatorsField(required=False)
    pinned = serializers.BooleanField(required=False)
    shared = serializers.BooleanField(required=False)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=MAX_SAVED_VIEW_TAG_LENGTH, trim_whitespace=False),
        required=False,
        max_length=MAX_SAVED_VIEW_TAGS,
        error_messages={"max_length": "You can select up to 50 tags."},
    )
    folder = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=MAX_SAVED_VIEW_FOLDER_LENGTH,
        trim_whitespace=False,
        error_messages={"max_length": "Folder must be 4000 characters or fewer."},
    )

    def to_internal_value(self, data: object) -> dict[str, object]:
        if not isinstance(data, dict):
            raise serializers.ValidationError("Filters must be an object")
        unsupported_keys = data.keys() - SAVED_VIEW_FILTER_KEYS
        if unsupported_keys:
            raise serializers.ValidationError("Filters contain unsupported fields.")
        if "search" in data and not isinstance(data["search"], str):
            raise serializers.ValidationError("Search must be a string.")
        if isinstance(data.get("search"), str) and len(cast(str, data["search"])) > MAX_SAVED_VIEW_FILTER_STRING_LENGTH:
            raise serializers.ValidationError("Search must be 200 characters or fewer.")
        if "pinned" in data and not isinstance(data["pinned"], bool):
            raise serializers.ValidationError("Pinned must be true or false.")
        if "shared" in data and not isinstance(data["shared"], bool):
            raise serializers.ValidationError("Shared must be true or false.")
        if "tags" in data and (
            not isinstance(data["tags"], list) or any(not isinstance(tag, str) for tag in data["tags"])
        ):
            raise serializers.ValidationError("Tags must be a list of strings.")
        if isinstance(data.get("tags"), list):
            tags = cast(list[str], data["tags"])
            if len(tags) > MAX_SAVED_VIEW_TAGS:
                raise serializers.ValidationError("You can select up to 50 tags.")
            if any(len(tag) > MAX_SAVED_VIEW_TAG_LENGTH for tag in tags):
                raise serializers.ValidationError("Tags must be 100 characters or fewer.")
        if "folder" in data and data["folder"] is not None and not isinstance(data["folder"], str):
            raise serializers.ValidationError("Folder must be a string or null.")
        if isinstance(data.get("folder"), str) and len(cast(str, data["folder"])) > MAX_SAVED_VIEW_FOLDER_LENGTH:
            raise serializers.ValidationError("Folder must be 4000 characters or fewer.")
        attrs = cast(dict[str, object], super().to_internal_value(data))
        if not has_saved_view_filters(attrs):
            raise serializers.ValidationError("Add at least one filter before saving a view.")
        if (
            len(json.dumps(attrs, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            > MAX_SAVED_VIEW_FILTER_BYTES
        ):
            raise serializers.ValidationError("Saved view filters are too large.")
        return attrs


class DashboardSavedViewWriteSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=200, help_text="Name shown in the dashboard list view picker.")
    filters = DashboardSavedViewFiltersSerializer(help_text="Dashboard list filters stored by this view.")
    scope = serializers.ChoiceField(
        choices=DashboardSavedView.Scope.choices,
        default=DashboardSavedView.Scope.PRIVATE,
        help_text="Whether only the creator or all team members can use this view.",
    )

    class Meta:
        model = DashboardSavedView
        fields = ["name", "filters", "scope"]


class DashboardSavedViewSerializer(DashboardSavedViewWriteSerializer):
    can_change_scope = serializers.SerializerMethodField(
        help_text="Whether the current user can change this view's visibility."
    )

    def get_can_change_scope(self, instance: DashboardSavedView) -> bool:
        return instance.can_change_scope(cast(User, self.context["request"].user))

    class Meta(DashboardSavedViewWriteSerializer.Meta):
        fields = ["id", "name", "filters", "scope", "created_at", "updated_at", "created_by", "can_change_scope"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]


class DashboardSavedViewListQuerySerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=DashboardSavedView.Scope.choices,
        required=False,
        help_text="Return saved views with this visibility scope.",
    )


class DashboardSavedViewPagination(CursorPagination):
    page_size = 100
    page_size_query_param = "limit"
    max_page_size = 100
    ordering = ("name", "id")


class DashboardSavedViewPermission(BasePermission):
    message = "You don't have permission to access dashboard saved views."

    @staticmethod
    def _saved_views_team(view: APIView) -> Team:
        viewset = cast("DashboardSavedViewViewSet", view)
        return viewset.team.parent_team or viewset.team

    def has_permission(self, request: Request, view: APIView) -> bool:
        team = self._saved_views_team(view)
        if not dashboard_saved_views_enabled(team=team):
            return False
        access_level: AccessControlLevel = "viewer" if request.method in SAFE_METHODS else "editor"
        return UserAccessControl(user=cast(User, request.user), team=team).check_access_level_for_resource(
            "dashboard", access_level
        )

    def has_object_permission(self, request: Request, view: APIView, obj: DashboardSavedView) -> bool:
        access_level: AccessControlLevel = "viewer" if request.method in SAFE_METHODS else "editor"
        return UserAccessControl(
            user=cast(User, request.user), team=self._saved_views_team(view)
        ).check_access_level_for_resource("dashboard", access_level)


class DashboardSavedViewViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [DashboardSavedViewPermission]
    pagination_class = DashboardSavedViewPagination
    queryset: QuerySet[DashboardSavedView] = DashboardSavedView.all_teams.all()
    serializer_class = DashboardSavedViewSerializer

    def get_serializer_class(self) -> type[DashboardSavedViewWriteSerializer | DashboardSavedViewSerializer]:
        if self.action == "create":
            return DashboardSavedViewWriteSerializer
        return DashboardSavedViewSerializer

    @extend_schema(parameters=[DashboardSavedViewListQuerySerializer])
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        query = DashboardSavedViewListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=DashboardSavedViewWriteSerializer, responses={status.HTTP_201_CREATED: DashboardSavedViewSerializer}
    )
    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = DashboardSavedViewWriteSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        response_serializer = DashboardSavedViewSerializer(serializer.instance, context=self.get_serializer_context())
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def safely_get_queryset(self, queryset: QuerySet[DashboardSavedView]) -> QuerySet[DashboardSavedView]:
        queryset = queryset.filter(team_id=self.canonical_team_id).filter(
            models.Q(scope=DashboardSavedView.Scope.TEAM)
            | models.Q(scope=DashboardSavedView.Scope.PRIVATE, created_by=cast(User, self.request.user))
        )
        scope = self.request.query_params.get("scope")
        return queryset.filter(scope=scope) if scope else queryset

    @property
    def canonical_team_id(self) -> int:
        return self.team.parent_team_id or self.team.id

    def _should_skip_parents_filter(self) -> bool:
        return True

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        serializer = cast(DashboardSavedViewWriteSerializer, serializer)
        scope = cast(DashboardSavedView.Scope, serializer.validated_data.get("scope", DashboardSavedView.Scope.PRIVATE))
        user = cast(User, self.request.user)
        limit = MAX_TEAM_SAVED_VIEWS if scope == DashboardSavedView.Scope.TEAM else MAX_PERSONAL_SAVED_VIEWS
        views = DashboardSavedView.objects.for_team(self.canonical_team_id).filter(scope=scope)
        if scope == DashboardSavedView.Scope.PRIVATE:
            views = views.filter(created_by=user)

        with transaction.atomic():
            Team.objects.select_for_update().get(pk=self.canonical_team_id)
            if views.count() >= limit:
                raise serializers.ValidationError(f"You can save up to {limit} {scope} dashboard views.")
            instance = serializer.save(team_id=self.canonical_team_id, created_by=user)
        report_user_action(
            self.request.user,
            "dashboard saved view created",
            {
                "saved_view_id": str(instance.id),
                "scope": instance.scope,
                **saved_view_filter_properties(cast(DashboardSavedViewFilters, instance.filters)),
                **saved_view_creator_properties(team_id=self.canonical_team_id, user_id=user.id),
            },
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        serializer = cast(DashboardSavedViewWriteSerializer, serializer)
        existing_view = cast(DashboardSavedView, serializer.instance)
        try:
            with transaction.atomic():
                locked_view = DashboardSavedView.all_teams.select_for_update().get(pk=existing_view.pk)
                scope = cast(DashboardSavedView.Scope | None, serializer.validated_data.get("scope"))
                if not locked_view.can_modify(cast(User, self.request.user)):
                    raise PermissionDenied("You don't have permission to update this private saved view.")
                if (
                    scope is not None
                    and scope != locked_view.scope
                    and not locked_view.can_change_scope(cast(User, self.request.user))
                ):
                    raise PermissionDenied("Only the creator can change a shared saved view's visibility.")
                serializer.instance = locked_view
                instance = serializer.save()
        except DashboardSavedView.DoesNotExist:
            raise NotFound()
        report_user_action(
            self.request.user,
            "dashboard saved view updated",
            {
                "saved_view_id": str(instance.id),
                "scope": instance.scope,
                "changed_fields": sorted(serializer.validated_data.keys()),
                **saved_view_filter_properties(cast(DashboardSavedViewFilters, instance.filters)),
            },
            team=self.team,
            request=self.request,
        )

    def perform_destroy(self, instance: DashboardSavedView) -> None:
        try:
            with transaction.atomic():
                locked_view = DashboardSavedView.all_teams.select_for_update().get(pk=instance.pk)
                if not locked_view.can_modify(cast(User, self.request.user)):
                    raise PermissionDenied("You don't have permission to delete this private saved view.")
                scope = locked_view.scope
                locked_view.delete()
        except DashboardSavedView.DoesNotExist:
            raise NotFound()
        report_user_action(
            self.request.user,
            "dashboard saved view deleted",
            {"saved_view_id": str(instance.id), "scope": scope},
            team=self.team,
            request=self.request,
        )
