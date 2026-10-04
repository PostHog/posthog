from typing import Any, cast

from django.db import transaction
from django.db.models import Case, Q, QuerySet, When
from django.db.models.functions import Lower

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.file_system.access_levels import FileSystemAccessLevelSerializerMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.models.file_system.constants import DEFAULT_SURFACE, RETIRED_FILE_SYSTEM_TYPES, surface_q
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut, lock_user_shortcuts


class FileSystemShortcutSerializer(FileSystemAccessLevelSerializerMixin, serializers.ModelSerializer):
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
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "user_access_level",
        ]
        extra_kwargs = {
            "path": {"help_text": "Display path of the shortcut in the sidebar."},
            "type": {"help_text": "Type of the linked item (e.g. 'folder', 'insight'), or blank."},
            "ref": {"help_text": "Reference to the linked item, scoped to its type. Null for href-only shortcuts."},
            "href": {
                "help_text": "Destination URL the shortcut opens. Null when the shortcut points at an item by ref."
            },
            "order": {"help_text": "Display order within the user's shortcut list, ascending."},
        }

    def update(self, instance: FileSystemShortcut, validated_data: dict[str, Any]) -> FileSystemShortcut:
        instance.team_id = self.context["team_id"]
        instance.user = self.context["request"].user
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> FileSystemShortcut:
        request = self.context["request"]
        team = self.context["get_team"]()
        with transaction.atomic():
            # Two stars added at once would otherwise read the same last order and share it.
            lock_user_shortcuts(team.pk, request.user.pk)
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
                surface=self.context.get("file_system_surface", DEFAULT_SURFACE),
                **validated_data,
            )
        return file_system_shortcut


class FileSystemShortcutReorderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="IDs of the current user's shortcuts in the desired display order.",
    )


class FileSystemShortcutBulkItemSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="Display path of the shortcut in the sidebar.")
    type = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=100,
        help_text="Type of the linked item (e.g. 'folder', 'insight'), or blank.",
    )
    ref = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=4000,
        help_text="Reference to the linked item, scoped to its type. Null for href-only shortcuts.",
    )
    href = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Destination URL the shortcut opens. Null when the shortcut points at an item by ref.",
    )


class FileSystemShortcutBulkUpdateSerializer(serializers.Serializer):
    add = serializers.ListField(
        child=FileSystemShortcutBulkItemSerializer(),
        required=False,
        default=list,
        max_length=500,
        help_text="Shortcuts to create, appended to the end of the current order in the given sequence. "
        "An item identical to a shortcut the user already has is skipped.",
    )
    remove_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        max_length=500,
        help_text="IDs of the current user's shortcuts to delete.",
    )


@extend_schema(extensions={"x-product": "core"})
class FileSystemShortcutViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = FileSystemShortcut.objects.all()
    scope_object = "file_system_shortcut"
    serializer_class = FileSystemShortcutSerializer
    # Product surface these shortcuts serve. Subclass and override to expose a different surface
    # (e.g. "desktop") on its own route. The default surface also matches legacy NULL rows.
    file_system_surface: str = DEFAULT_SURFACE

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["file_system_surface"] = self.file_system_surface
        return context

    def _scope_by_project(self, queryset):
        return queryset.filter(surface_q(self.file_system_surface), team__project_id=self.team.project_id)

    def _scope_by_project_and_environment(self, queryset: QuerySet) -> QuerySet:
        queryset = self._scope_by_project(queryset)
        # type !~ 'hog_function/.*' or team = $current
        queryset = queryset.filter(Q(**self.parent_query_kwargs) | ~Q(type__startswith="hog_function/"))
        return queryset

    def _filter_queryset_by_parents_lookups(self, queryset):
        return self._scope_by_project(queryset)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = self._scope_by_project_and_environment(queryset).filter(user=self.request.user)
        if self.action == "list":
            queryset = queryset.exclude(type__in=RETIRED_FILE_SYSTEM_TYPES)
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

        user_shortcuts_qs = FileSystemShortcut.objects.filter(
            surface_q(self.file_system_surface), team=self.team, user=cast(User, request.user)
        )
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

    @extend_schema(
        request=FileSystemShortcutBulkUpdateSerializer,
        responses={200: OpenApiResponse(response=FileSystemShortcutSerializer(many=True))},
        description="Create and delete several of the current user's shortcuts in one transaction, then return "
        "the full shortcut list in display order. Any unknown ID in `remove_ids` rejects the whole request.",
    )
    @action(detail=False, methods=["post"], url_path="bulk_update", pagination_class=None)
    def bulk_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = FileSystemShortcutBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items: list[dict[str, Any]] = serializer.validated_data["add"]
        remove_ids = {str(uuid) for uuid in serializer.validated_data["remove_ids"]}

        user = cast(User, request.user)
        user_shortcuts_qs = FileSystemShortcut.objects.filter(
            surface_q(self.file_system_surface), team=self.team, user=user
        )
        with transaction.atomic():
            # Overlapping saves would otherwise read the same list and add duplicates or reuse an order.
            lock_user_shortcuts(self.team.pk, user.pk)
            existing = list(user_shortcuts_qs.values_list("id", "path", "type", "ref", "href", "order"))
            unknown = sorted(remove_ids - {str(row[0]) for row in existing})
            if unknown:
                return Response(
                    {"detail": "Unknown shortcut ids", "unknown_ids": unknown},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            kept = [row for row in existing if str(row[0]) not in remove_ids]
            seen = {(path, kind or "", ref, href) for _, path, kind, ref, href, _ in kept}
            next_order = max((row[5] for row in kept), default=0) + 1
            to_create: list[FileSystemShortcut] = []
            for item in items:
                key = (item["path"], item["type"], item["ref"], item["href"])
                if key in seen:
                    continue
                seen.add(key)
                to_create.append(
                    FileSystemShortcut(
                        team=self.team,
                        user=user,
                        surface=self.file_system_surface,
                        order=next_order + len(to_create),
                        **item,
                    )
                )

            if remove_ids:
                user_shortcuts_qs.filter(id__in=remove_ids).delete()
            FileSystemShortcut.objects.bulk_create(to_create)

        refreshed = self.filter_queryset(self.get_queryset())
        return Response(self.get_serializer(refreshed, many=True).data)
