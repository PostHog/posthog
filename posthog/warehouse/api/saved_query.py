from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import DataWarehouseSavedQuery, DataWarehouseViewLink
from posthog.api.shared import UserBasicSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.hogql.database.database import serialize_fields, SerializedField

from posthog.models import User
from typing import Any, List

from rest_framework import request, response, status


class DataWarehouseSavedQuerySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    columns = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DataWarehouseSavedQuery
        fields = ["id", "deleted", "name", "query", "created_by", "created_at", "columns"]
        read_only_fields = ["id", "created_by", "created_at", "columns"]

    def get_columns(self, view: DataWarehouseSavedQuery) -> List[SerializedField]:
        return serialize_fields(view.hogql_definition().fields)

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        view = DataWarehouseSavedQuery(**validated_data)
        # The columns will be inferred from the query
        try:
            view.columns = view.get_columns()
        except Exception as err:
            raise serializers.ValidationError(str(err))

        view.save()
        return view

    def update(self, instance: Any, validated_data: Any) -> Any:
        view = super().update(instance, validated_data)

        try:
            view.columns = view.get_columns()
        except Exception as err:
            raise serializers.ValidationError(str(err))
        view.save()
        return view


class DataWarehouseSavedQueryViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Tables.
    """

    queryset = DataWarehouseSavedQuery.objects.all()
    serializer_class = DataWarehouseSavedQuerySerializer
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        if self.action == "list":
            return (
                self.queryset.filter(team_id=self.team_id)
                .exclude(deleted=True)
                .prefetch_related("created_by")
                .order_by(self.ordering)
            )

        return self.queryset.filter(team_id=self.team_id).prefetch_related("created_by").order_by(self.ordering)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        instance: DataWarehouseSavedQuery = self.get_object()
        # Remove related view links
        DataWarehouseViewLink.objects.filter(table=instance.name).delete()
        self.perform_destroy(instance)
        return response.Response(status=status.HTTP_204_NO_CONTENT)
