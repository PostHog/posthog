from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import DataWarehouseView
from posthog.api.shared import UserBasicSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.query import process_query
from posthog.models.team import Team

from posthog.models import User
from typing import Dict


class DataWarehouseViewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    columns = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DataWarehouseView
        fields = ["id", "deleted", "name", "query", "created_by", "created_at", "columns"]
        read_only_fields = ["id", "created_by", "created_at", "columns"]

    def get_columns(self, table: DataWarehouseView) -> Dict[str, str]:
        # implement
        # return serialize_fields(table.hogql_definition().fields)
        return

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        table = DataWarehouseView(**validated_data)

        query_json = validated_data.get("query")
        if query_json:
            team = Team.objects.get(id=self.context["team_id"])
            response = process_query(team, query_json)
            columns = response.get("columns")
            types = response.get("types")
            view_types = dict(zip(columns, types))
            table.columns = view_types

        table.save()
        return table


class DatawarehouseViewViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Tables.
    """

    queryset = DataWarehouseView.objects.all()
    serializer_class = DataWarehouseViewSerializer
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
