from typing import Optional

from rest_framework import filters, serializers, viewsets
from rest_framework.exceptions import NotAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.hogql.database.database import create_hogql_database
from posthog.models import User
from posthog.warehouse.models import DataWarehouseSavedQuery, DataWarehouseViewLink


class ViewLinkSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    saved_query_id = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = DataWarehouseViewLink
        fields = [
            "id",
            "deleted",
            "table",
            "created_by",
            "created_at",
            "saved_query_id",
            "saved_query",
            "to_join_key",
            "from_join_key",
        ]
        read_only_fields = ["id", "created_by", "created_at", "saved_query"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        to_join_key = validated_data.get("to_join_key")
        from_join_key = validated_data.get("from_join_key")
        table = validated_data.get("table")

        self._validate_join_key(from_join_key, table, self.context["team_id"])
        self._validate_saved_query(validated_data["saved_query_id"], to_join_key, self.context["team_id"])

        view_link = DataWarehouseViewLink.objects.create(**validated_data)

        return view_link

    def _validate_saved_query(self, saved_query_id: str, join_key: Optional[str], team_id: int) -> None:
        if not join_key:
            raise serializers.ValidationError("View column must have a join key.")

        try:
            saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id, team_id=team_id)
        except DataWarehouseSavedQuery.DoesNotExist:
            raise serializers.ValidationError("Saved query does not exist.")

        try:
            saved_query_instance = saved_query.hogql_definition()
            saved_query_instance.fields[join_key]
        except Exception:
            raise serializers.ValidationError(f"Invalid join key: {join_key}")

        return

    def _validate_join_key(self, join_key: Optional[str], table: Optional[str], team_id: int) -> None:
        if not join_key:
            raise serializers.ValidationError("View column must have a join key.")

        if not table:
            raise serializers.ValidationError("View column must have a table.")

        database = create_hogql_database(team_id)
        try:
            table_instance = database.get_table(table)
        except Exception:
            raise serializers.ValidationError(f"Invalid table: {table}")

        try:
            table_instance.fields[join_key]
        except Exception:
            raise serializers.ValidationError(f"Invalid join key: {join_key}")

        return


class ViewLinkViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete View Columns.
    """

    scope_object = "INTERNAL"
    queryset = DataWarehouseViewLink.objects.all()
    serializer_class = ViewLinkSerializer
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
