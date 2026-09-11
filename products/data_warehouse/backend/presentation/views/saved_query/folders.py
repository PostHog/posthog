"""Saved-query folders: the serializer and the viewset that organize views in the SQL editor."""

import uuid
from typing import Any

from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce

from rest_framework import request, response, serializers, status, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.access_control.backend.presentation.access_control import (
    AccessControlViewSetMixin,
    UserAccessControlSerializerMixin,
)
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_tools.backend.facade.models import DataWarehouseSavedQueryFolder

from . import lifecycle


class DataWarehouseSavedQueryFolderSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    view_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DataWarehouseSavedQueryFolder
        fields = ["id", "name", "created_at", "created_by", "view_count", "user_access_level"]
        read_only_fields = ["id", "created_at", "created_by", "view_count", "user_access_level"]
        extra_kwargs = {
            "name": {
                "help_text": "Display name for the folder used to organize saved queries in the SQL editor sidebar."
            }
        }

    def validate_name(self, name: str) -> str:
        normalized_name = name.strip()
        if not normalized_name:
            raise serializers.ValidationError("Folder name cannot be empty.")

        team_id = self.context["team_id"]
        queryset = DataWarehouseSavedQueryFolder.objects.filter(team_id=team_id, name=normalized_name)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError("A folder with this name already exists.")

        return normalized_name


class DataWarehouseSavedQueryFolderViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "warehouse_view"
    queryset = DataWarehouseSavedQueryFolder.objects.all()
    serializer_class = DataWarehouseSavedQueryFolderSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]
    ordering = "name"

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(team_id=self.team_id)
            .select_related("created_by")
            .annotate(
                view_count=Coalesce(
                    Subquery(
                        DataWarehouseSavedQuery.objects.filter(folder=OuterRef("pk"), deleted=False)
                        .order_by()
                        .values("folder")
                        .annotate(c=Count("id"))
                        .values("c"),
                        output_field=IntegerField(),
                    ),
                    0,
                )
            )
            .order_by(self.ordering)
        )

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id, created_by=self.request.user)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        from products.data_modeling.backend.facade.api import HasDependentsError

        folder: DataWarehouseSavedQueryFolder = self.get_object()
        remaining_queries = {
            saved_query.id: saved_query
            for saved_query in DataWarehouseSavedQuery.objects.filter(folder=folder, deleted=False).select_related(
                "managed_viewset", "folder"
            )
        }

        while remaining_queries:
            deleted_ids: list[uuid.UUID] = []

            for saved_query_id, saved_query in remaining_queries.items():
                try:
                    lifecycle.delete_saved_query(saved_query)
                    deleted_ids.append(saved_query_id)
                except HasDependentsError:
                    continue

            if not deleted_ids:
                blocked_names = ", ".join(sorted(saved_query.name for saved_query in remaining_queries.values()))
                raise serializers.ValidationError(
                    f"Cannot delete this folder because these views still have dependencies outside the folder: {blocked_names}"
                )

            for saved_query_id in deleted_ids:
                remaining_queries.pop(saved_query_id, None)

        folder.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)
