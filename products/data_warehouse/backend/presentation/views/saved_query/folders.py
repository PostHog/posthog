"""Saved-query folders: the serializer and the viewset that organize views in the SQL editor."""

import uuid
from typing import Any

from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce

from rest_framework import request, response, serializers, status, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.permissions import is_service_auth

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
            .annotate(view_count=Coalesce(self._visible_view_count(), 0))
            .order_by(self.ordering)
        )

    def _visible_view_count(self) -> Subquery:
        """Counts only the views this caller may list.

        Access control applies to the folder rows, never to what a folder annotation counts, so an
        unfiltered count answers "a view you may not read is in here" - the thing the grant is there
        to withhold. Service credentials skip the filter for the same reason the list path skips it:
        their synthetic user cannot be compared against `created_by`.
        """
        views = DataWarehouseSavedQuery.objects.filter(folder=OuterRef("pk")).exclude(deleted=True)
        if not is_service_auth(self.request):
            # The resource is passed rather than inferred: an unmapped model name filters nothing.
            views = self.user_access_control.filter_queryset_by_access_level(views, resource="warehouse_view")
        return Subquery(
            views.order_by().values("folder").annotate(c=Count("id")).values("c"),
            output_field=IntegerField(),
        )

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id, created_by=self.request.user)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        from products.data_modeling.backend.facade.api import dependent_saved_query_ids

        folder: DataWarehouseSavedQueryFolder = self.get_object()
        with transaction.atomic():
            # A view moved into the folder after we list its contents would survive `folder.delete()`
            # with `folder=NULL`; holding the row makes that move wait and then fail its FK check.
            DataWarehouseSavedQueryFolder.objects.select_for_update().get(pk=folder.pk)
            saved_queries = list(
                DataWarehouseSavedQuery.objects.filter(folder=folder)
                .exclude(deleted=True)
                .select_related("managed_viewset", "folder")
            )

            # `get_object()` checked the folder only; each view carries its own grant.
            for saved_query in saved_queries:
                self.check_object_permissions(request, saved_query)

            in_folder_ids = {saved_query.id for saved_query in saved_queries}
            dependents = dependent_saved_query_ids(self.team_id, in_folder_ids)
            blocked_names = sorted(
                saved_query.name for saved_query in saved_queries if dependents[saved_query.id] - in_folder_ids
            )
            if blocked_names:
                raise serializers.ValidationError(
                    f"Cannot delete this folder because these views still have dependencies outside the folder: {', '.join(blocked_names)}"
                )

            self._delete_in_dependency_order(saved_queries)
            folder.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _delete_in_dependency_order(saved_queries: list[DataWarehouseSavedQuery]) -> None:
        """Delete dependents before their sources; the caller has already ruled out outside dependents."""
        from products.data_modeling.backend.facade.api import HasDependentsError

        remaining = {saved_query.id: saved_query for saved_query in saved_queries}
        while remaining:
            deleted_ids: list[uuid.UUID] = []
            for saved_query_id, saved_query in remaining.items():
                try:
                    lifecycle.delete_saved_query(saved_query)
                    deleted_ids.append(saved_query_id)
                except HasDependentsError:
                    continue
            if not deleted_ids:
                raise serializers.ValidationError("Cannot delete this folder because its views still have dependencies")
            for saved_query_id in deleted_ids:
                remaining.pop(saved_query_id, None)
