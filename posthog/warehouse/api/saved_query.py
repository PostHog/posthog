from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import DatawarehouseSavedQuery
from posthog.api.shared import UserBasicSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.hogql.database.database import Database
from posthog.hogql.hogql import HogQLContext

from posthog.models import User
from typing import Any


class DatawarehouseSavedQuerySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DatawarehouseSavedQuery
        fields = ["id", "deleted", "name", "query", "created_by", "created_at", "columns"]
        read_only_fields = ["id", "created_by", "created_at", "columns"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        self._validate_name(validated_data["name"])

        view = DatawarehouseSavedQuery(**validated_data)
        # The columns will be inferred from the query
        try:
            view.columns = view.get_columns()
        except Exception as err:
            raise serializers.ValidationError(str(err))

        view.save()
        return view

    def update(self, instance: Any, validated_data: Any) -> Any:
        view = super().update(instance, validated_data)
        self._validate_name(validated_data["name"])

        try:
            view.columns = view.get_columns()
        except Exception as err:
            raise serializers.ValidationError(str(err))
        view.save()
        return view

    def _validate_name(self, name):
        posthog_table_names = [
            table.to_printed_clickhouse(context=HogQLContext(team_id=self.context["team_id"]))
            for table in Database._tables
        ]
        if name in posthog_table_names:
            raise serializers.ValidationError(str("View name cannot override a PostHog table name."))


class DatawarehouseSavedQueryViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Tables.
    """

    queryset = DatawarehouseSavedQuery.objects.all()
    serializer_class = DatawarehouseSavedQuerySerializer
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
