from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import DataWarehouseSavedQuery
from posthog.api.shared import UserBasicSerializer
from posthog.api.routing import StructuredViewSetMixin

from posthog.models import User
from typing import Any


class DataWarehouseSavedQuerySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataWarehouseSavedQuery
        fields = ["id", "deleted", "name", "query", "created_by", "created_at", "columns"]
        read_only_fields = ["id", "created_by", "created_at", "columns"]

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
