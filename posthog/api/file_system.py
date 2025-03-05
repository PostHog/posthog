from typing import Any, cast

from django.db.models import QuerySet
from rest_framework import filters, serializers, viewsets, pagination, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.file_system import FileSystem, save_unfiled_files, split_path
from posthog.models.user import User
from posthog.models.team import Team
from posthog.schema import FileSystemType


class FileSystemSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = FileSystem
        fields = [
            "id",
            "path",
            "depth",
            "type",
            "ref",
            "href",
            "meta",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "depth",
            "created_at",
            "created_by",
        ]

    def update(self, instance: FileSystem, validated_data: dict[str, Any]) -> FileSystem:
        instance.team_id = self.context["team_id"]
        if "path" in validated_data:
            instance.depth = len(split_path(validated_data["path"]))
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> FileSystem:
        request = self.context["request"]
        team = self.context["get_team"]()

        full_path = validated_data["path"]
        segments = split_path(full_path)

        for depth_index in range(1, len(segments)):
            parent_path = "/".join(segments[:depth_index])
            folder_exists = FileSystem.objects.filter(team=team, path=parent_path).exists()
            if not folder_exists:
                FileSystem.objects.create(
                    team=team,
                    path=parent_path,
                    depth=depth_index,
                    type="folder",
                    created_by=request.user,
                )

        depth = len(segments)
        file_system = FileSystem.objects.create(
            team=team,
            created_by=request.user,
            depth=depth,
            **validated_data,
        )

        return file_system


class FileSystemsLimitOffsetPagination(pagination.LimitOffsetPagination):
    default_limit = 11


class UnfiledFilesQuerySerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=[(choice.value, choice.value) for choice in FileSystemType], required=False, allow_blank=True
    )


class FileSystemViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "file_system"
    queryset = FileSystem.objects.select_related("created_by")
    serializer_class = FileSystemSerializer
    filter_backends = [filters.SearchFilter]
    pagination_class = FileSystemsLimitOffsetPagination
    search_fields = ["path"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team=self.team)

        depth_param = self.request.query_params.get("depth")
        parent_param = self.request.query_params.get("parent")

        if depth_param is not None:
            try:
                depth_value = int(depth_param)
                queryset = queryset.filter(depth=depth_value)
            except ValueError:
                pass

        if parent_param:
            queryset = queryset.filter(path__startswith=f"{parent_param}/")

        if self.action == "list":
            queryset = queryset.order_by("path")

        return queryset

    @action(methods=["GET"], detail=False)
    def unfiled(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query_serializer = UnfiledFilesQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        file_type = query_serializer.validated_data.get("type")
        files = save_unfiled_files(self.team, cast(User, request.user), file_type)

        retroactively_fix_folders_and_depth(self.team, cast(User, request.user))

        return Response(
            {
                "results": FileSystemSerializer(files, many=True).data,
                "count": len(files),
            },
            status=status.HTTP_200_OK,
        )


def retroactively_fix_folders_and_depth(team: Team, user: User) -> None:
    """
    For all existing FileSystem rows in `team`, ensure that any missing parent
    folders are created. Also ensure `depth` is correct.
    """

    # TODO: this needs some concurrency controls or a unique index

    existing_paths = set(FileSystem.objects.filter(team=team).values_list("path", flat=True))

    folders_to_create = []
    items_to_update = []

    all_files = FileSystem.objects.filter(team=team).select_related("created_by")
    for file_obj in all_files:
        segments = split_path(file_obj.path)
        correct_depth = len(segments)

        # If depth is missing or incorrect, fix it
        if file_obj.depth != correct_depth:
            file_obj.depth = correct_depth
            items_to_update.append(file_obj)

        # Create missing parent folders
        # e.g. for path "a/b/c/d/e", the parent folders are:
        #  "a" (depth=1), "a/b" (depth=2), "a/b/c" (depth=3), "a/b/c/d" (depth=4)
        for depth_index in range(1, len(segments)):
            parent_path = "/".join(segments[:depth_index])
            if parent_path not in existing_paths:
                # Mark that we have it now (so we don't create duplicates)
                existing_paths.add(parent_path)
                folders_to_create.append(
                    FileSystem(
                        team=team,
                        path=parent_path,
                        depth=depth_index,
                        type="folder",
                        created_by=user,
                    )
                )

    if folders_to_create:
        FileSystem.objects.bulk_create(folders_to_create)

    if items_to_update:
        for item in items_to_update:
            item.save()
