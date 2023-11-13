from rest_framework import request, response, status
from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import (
    DataWarehouseTable,
    DataWarehouseCredential,
    DataWarehouseSavedQuery,
)
from posthog.hogql.database.database import serialize_fields, SerializedField
from posthog.api.shared import UserBasicSerializer
from posthog.api.routing import StructuredViewSetMixin

from posthog.models import User
from typing import Any, List


class CredentialSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataWarehouseCredential
        fields = ["id", "created_by", "created_at", "access_key", "access_secret"]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
        ]
        extra_kwargs = {"access_secret": {"write_only": "True"}}


class TableSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    credential = CredentialSerializer()
    columns = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DataWarehouseTable
        fields = [
            "id",
            "deleted",
            "name",
            "format",
            "created_by",
            "created_at",
            "url_pattern",
            "credential",
            "columns",
        ]
        read_only_fields = ["id", "created_by", "created_at", "columns"]

    def get_columns(self, table: DataWarehouseTable) -> List[SerializedField]:
        return serialize_fields(table.hogql_definition().fields)

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        if validated_data.get("credential"):
            validated_data["credential"] = DataWarehouseCredential.objects.create(
                team_id=self.context["team_id"],
                access_key=validated_data["credential"]["access_key"],
                access_secret=validated_data["credential"]["access_secret"],
            )
        table = DataWarehouseTable(**validated_data)
        try:
            table.columns = table.get_columns()
        except Exception as err:
            raise serializers.ValidationError(str(err))
        table.save()
        return table


class TableViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Tables.
    """

    queryset = DataWarehouseTable.objects.all()
    serializer_class = TableSerializer
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
        instance: DataWarehouseTable = self.get_object()
        DataWarehouseSavedQuery.objects.filter(external_tables__icontains=instance.name).delete()
        self.perform_destroy(instance)

        return response.Response(status=status.HTTP_204_NO_CONTENT)
