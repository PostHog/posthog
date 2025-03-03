from typing import Any, cast

from django.db.models import QuerySet
from rest_framework import filters, serializers, viewsets, pagination, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.file_system import FileSystem, save_unfiled_files
from posthog.models.user import User
from posthog.schema import FileSystemType


class FileSystemSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = FileSystem
        fields = [
            "id",
            "path",
            "type",
            "ref",
            "href",
            "meta",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
        ]

    def update(self, instance: FileSystem, validated_data: dict[str, Any]) -> FileSystem:
        instance.team_id = self.context["team_id"]
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> FileSystem:
        request = self.context["request"]
        team = self.context["get_team"]()
        file_system = FileSystem.objects.create(
            team_id=team.id,
            created_by=request.user,
            **validated_data,
        )
        return file_system


class FileSystemsLimitOffsetPagination(pagination.LimitOffsetPagination):
    default_limit = 20000


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

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            queryset = queryset.order_by("path")
        return queryset

    def _filter_queryset_by_parents_lookups(self, queryset):
        return queryset.filter(team=self.team)

    @action(methods=["GET"], detail=False)
    def unfiled(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query_serializer = UnfiledFilesQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        file_type = query_serializer.validated_data.get("type")
        files = save_unfiled_files(self.team, cast(User, request.user), file_type)

        return Response(
            {
                "results": FileSystemSerializer(files, many=True).data,
                "count": len(files),
            },
            status=status.HTTP_200_OK,
        )
