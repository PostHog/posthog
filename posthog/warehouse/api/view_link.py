from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import DataWarehouseViewLink
from posthog.api.shared import UserBasicSerializer
from posthog.api.routing import StructuredViewSetMixin

from posthog.models import User, PropertyDefinition
from typing import Optional


class ViewLinkSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    saved_query_id = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = DataWarehouseViewLink
        fields = ["id", "deleted", "table", "created_by", "created_at", "saved_query_id", "saved_query", "join_key"]
        read_only_fields = ["id", "created_by", "created_at", "saved_query"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        join_key = validated_data.get("join_key")
        table = validated_data.get("table")

        self._validate_join_key(join_key, table)

        view_link = DataWarehouseViewLink.objects.create(**validated_data)

        columns = view_link.saved_query.get_columns()

        # TODO: table to number
        for name, _ in columns.items():
            PropertyDefinition.objects.create(
                team_id=validated_data["team_id"], type=table, name=name, view_link=view_link
            )
        return view_link

    def _validate_join_key(self, join_key: Optional[str], table: Optional[int]) -> None:
        if not join_key:
            raise serializers.ValidationError("View column must have a join key.")

        if not table:
            raise serializers.ValidationError("View column must have a table.")

        # TODO: validate join key against the

        return


class ViewLinkViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete View Columns.
    """

    queryset = DataWarehouseViewLink.objects.all()
    serializer_class = ViewLinkSerializer
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
