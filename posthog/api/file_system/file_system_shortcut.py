from typing import Any, cast

from django.db import transaction
from django.db.models import Case, Q, QuerySet, When
from django.db.models.functions import Lower

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut


class FileSystemShortcutSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileSystemShortcut
        fields = [
            "id",
            "path",
            "type",
            "ref",
            "href",
            "order",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]

    def update(self, instance: FileSystemShortcut, validated_data: dict[str, Any]) -> FileSystemShortcut:
        instance.team_id = self.context["team_id"]
        instance.user = self.context["request"].user
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> FileSystemShortcut:
        request = self.context["request"]
        team = self.context["get_team"]()
        # Place new shortcuts at the end of the user's current order so they don't jump
        # ahead of items the user has explicitly reordered.
        last_order = (
            FileSystemShortcut.objects.filter(team=team, user=request.user)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        validated_data.setdefault("order", (last_order or 0) + 1)
        file_system_shortcut = FileSystemShortcut.objects.create(
            team=team,
            user=request.user,
            **validated_data,
        )
        return file_system_shortcut


class FileSystemShortcutReorderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="IDs of the current user's shortcuts in the desired display order.",
    )


class FileSystemShortcutViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = FileSystemShortcut.objects.all()
    scope_object = "file_system_shortcut"
    serializer_class = FileSystemShortcutSerializer

    def _scope_by_project(self, queryset):
        return queryset.filter(team__project_id=self.team.project_id)

    def _scope_by_project_and_environment(self, queryset: QuerySet) -> QuerySet:
        queryset = self._scope_by_project(queryset)
        # type !~ 'hog_function/.*' or team = $current
        queryset = queryset.filter(Q(**self.parent_query_kwargs) | ~Q(type__startswith="hog_function/"))
        return queryset

    def _filter_queryset_by_parents_lookups(self, queryset):
        return self._scope_by_project(queryset)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = self._scope_by_project_and_environment(queryset).filter(user=self.request.user)
        ordering_param = self.request.GET.get("ordering", "")
        if ordering_param == "-created_at":
            return queryset.order_by("-created_at")
        if ordering_param == "created_at":
            return queryset.order_by("created_at")
        return queryset.order_by("order", Lower("path"))

    @extend_schema(
        request=FileSystemShortcutReorderSerializer,
        responses={200: OpenApiResponse(response=FileSystemShortcutSerializer(many=True))},
        description="Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.",
    )
    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = FileSystemShortcutReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ordered_ids = [str(uuid) for uuid in serializer.validated_data["ordered_ids"]]

        user_shortcuts_qs = FileSystemShortcut.objects.filter(team=self.team, user=cast(User, request.user))
        existing_ids = {str(pk) for pk in user_shortcuts_qs.values_list("id", flat=True)}
        unknown = [pk for pk in ordered_ids if pk not in existing_ids]
        if unknown:
            return Response(
                {"detail": "Unknown shortcut ids", "unknown_ids": unknown},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Write the new positions atomically. Items not included keep their current order.
        with transaction.atomic():
            user_shortcuts_qs.filter(id__in=ordered_ids).update(
                order=Case(
                    *[When(id=pk, then=index) for index, pk in enumerate(ordered_ids)],
                    default=0,
                )
            )

        refreshed = self.filter_queryset(self.get_queryset())
        return Response(self.get_serializer(refreshed, many=True).data)
