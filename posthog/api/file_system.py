from typing import Any, cast

from django.db import transaction
from django.db.models import QuerySet
from rest_framework import filters, serializers, viewsets, pagination, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.file_system.file_system import FileSystem, split_path, join_path
from posthog.models.file_system.unfiled_file_saver import save_unfiled_files
from posthog.models.user import User
from posthog.models.team import Team


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
            "shortcut",
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
                    shortcut=False,
                )

        if validated_data.get("shortcut") is None:
            validated_data["shortcut"] = False

        depth = len(segments)
        file_system = FileSystem.objects.create(
            team=team,
            created_by=request.user,
            depth=depth,
            **validated_data,
        )

        return file_system


class FileSystemsLimitOffsetPagination(pagination.LimitOffsetPagination):
    default_limit = 100


class UnfiledFilesQuerySerializer(serializers.Serializer):
    type = serializers.CharField(required=False, allow_blank=True)


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
        path_param = self.request.query_params.get("path")
        type_param = self.request.query_params.get("type")
        type__startswith_param = self.request.query_params.get("type__startswith")
        ref_param = self.request.query_params.get("ref")

        if depth_param is not None:
            try:
                depth_value = int(depth_param)
                queryset = queryset.filter(depth=depth_value)
            except ValueError:
                pass

        if self.action == "list":
            queryset = queryset.order_by("path")

        if path_param:
            queryset = queryset.filter(path=path_param)
        if parent_param:
            queryset = queryset.filter(path__startswith=f"{parent_param}/")
        if type_param:
            queryset = queryset.filter(type=type_param)
        if type__startswith_param:
            queryset = queryset.filter(type__startswith=type__startswith_param)
        if ref_param:
            queryset = queryset.filter(ref=ref_param)
            queryset = queryset.order_by("shortcut")  # override order

        if self.user_access_control:
            queryset = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)

        return queryset

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.type == "folder":
            qs = FileSystem.objects.filter(team=self.team, path__startswith=f"{instance.path}/")
            if self.user_access_control:
                qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)
            qs.delete()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["GET"], detail=False)
    def unfiled(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query_serializer = UnfiledFilesQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        file_type = query_serializer.validated_data.get("type")
        files = save_unfiled_files(self.team, cast(User, request.user), file_type)

        retroactively_fix_folders_and_depth(self.team, cast(User, request.user))

        if self.user_access_control:
            qs = FileSystem.objects.filter(id__in=[f.id for f in files])
            qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)
            file_count = qs.count()
        else:
            file_count = len(files)

        return Response(
            {
                "count": file_count,
            },
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True)
    def move(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        new_path = request.data.get("new_path")
        if not new_path:
            return Response({"detail": "new_path is required"}, status=status.HTTP_400_BAD_REQUEST)

        assure_parent_folders(new_path, self.team, cast(User, request.user))

        if instance.type == "folder":
            if new_path == instance.path:
                return Response({"detail": "Cannot move folder into itself"}, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                qs = FileSystem.objects.filter(team=self.team, path__startswith=f"{instance.path}/")
                if self.user_access_control:
                    qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)
                for file in qs:
                    file.path = new_path + file.path[len(instance.path) :]
                    file.depth = len(split_path(file.path))
                    file.save()

                targets = FileSystem.objects.filter(team=self.team, path=new_path).all()
                # We're a folder, and we're moving into a folder with the same name. Delete one.
                if any(target.type == "folder" for target in targets):
                    # TODO: merge access controls once those are in place
                    instance.delete()
                else:
                    instance.path = new_path
                    instance.depth = len(split_path(instance.path))
                    instance.save()

        else:
            instance.path = new_path
            instance.depth = len(split_path(instance.path))
            instance.save()

        return Response(
            FileSystemSerializer(instance).data,
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True)
    def link(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        new_path = request.data.get("new_path")
        if not new_path:
            return Response({"detail": "new_path is required"}, status=status.HTTP_400_BAD_REQUEST)

        assure_parent_folders(new_path, self.team, cast(User, request.user))

        if instance.type == "folder":
            if new_path == instance.path:
                return Response({"detail": "Cannot link folder into itself"}, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                qs = FileSystem.objects.filter(team=self.team, path__startswith=f"{instance.path}/")
                if self.user_access_control:
                    qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)

                for file in qs:
                    file.pk = None  # This removes the id
                    file.path = new_path + file.path[len(instance.path) :]
                    file.depth = len(split_path(file.path))
                    file.shortcut = True
                    file.save()  # A new instance is created with a new id

                targets = FileSystem.objects.filter(team=self.team, path=new_path).all()
                if any(target.type == "folder" for target in targets):
                    # We're a folder, and we're link into a folder with the same name. Noop.
                    pass
                else:
                    instance.pk = None  # This removes the id
                    instance.path = new_path
                    instance.depth = len(split_path(instance.path))
                    instance.shortcut = True
                    instance.save()  # A new instance is created with a new id

        else:
            instance.pk = None  # This removes the id
            instance.path = new_path + instance.path[len(instance.path) :]
            instance.depth = len(split_path(instance.path))
            instance.shortcut = True
            instance.save()  # A new instance is created with a new id

        return Response(
            FileSystemSerializer(instance).data,
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True)
    def count(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get count of all files in a folder."""
        instance = self.get_object()
        if instance.type != "folder":
            return Response({"detail": "Count can only be called on folders"}, status=status.HTTP_400_BAD_REQUEST)

        qs = FileSystem.objects.filter(team=self.team, path__startswith=f"{instance.path}/")
        if self.user_access_control:
            qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)

        return Response({"count": qs.count()}, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False)
    def count_by_path(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get count of all files in a folder."""
        path_param = self.request.query_params.get("path")
        if not path_param:
            return Response({"detail": "path parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        qs = FileSystem.objects.filter(team=self.team, path__startswith=f"{path_param}/")
        if self.user_access_control:
            qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)

        return Response({"count": qs.count()}, status=status.HTTP_200_OK)


def assure_parent_folders(path: str, team: Team, created_by: User) -> None:
    """
    Ensure that all parent folders for the given path exist for the provided team.
    For example, if the path is "a/b/c/d", this will ensure that "a", "a/b", and "a/b/c"
    all exist as folder type FileSystem entries.
    """
    segments = split_path(path)
    for depth_index in range(1, len(segments)):
        parent_path = join_path(segments[:depth_index])
        if not FileSystem.objects.filter(team=team, path=parent_path).exists():
            FileSystem.objects.create(
                team=team,
                path=parent_path,
                depth=depth_index,
                type="folder",
                created_by=created_by,
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
            parent_path = join_path(segments[:depth_index])
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
