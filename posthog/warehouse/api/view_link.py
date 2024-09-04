from typing import Optional

from rest_framework import filters, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.hogql.ast import Field
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.parser import parse_expr
from posthog.warehouse.models import DataWarehouseJoin


class ViewLinkSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataWarehouseJoin
        fields = [
            "id",
            "deleted",
            "created_by",
            "created_at",
            "source_table_name",
            "source_table_key",
            "joining_table_name",
            "joining_table_key",
            "field_name",
            "group_type_index",
        ]
        read_only_fields = ["id", "created_by", "created_at"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        source_table = validated_data.get("source_table_name")
        source_table_key = validated_data.get("source_table_key")
        joining_table = validated_data.get("joining_table_name")
        joining_table_key = validated_data.get("joining_table_key")
        field_name = validated_data.get("field_name")

        self._validate_join_key(source_table_key, source_table, self.context["team_id"])
        self._validate_join_key(joining_table_key, joining_table, self.context["team_id"])
        self._validate_key_uniqueness(field_name=field_name, table_name=source_table, team_id=self.context["team_id"])
        self._validate_group_type_index(
            group_type_index=validated_data.get("group_type_index"), source_table=source_table
        )

        view_link = DataWarehouseJoin.objects.create(**validated_data)

        return view_link

    def _validate_key_uniqueness(self, field_name: str, table_name: str, team_id: int) -> None:
        if field_name is None:
            raise serializers.ValidationError("Field name must not be empty.")

        database = create_hogql_database(team_id)
        table = database.get_table(table_name)
        field = table.fields.get(field_name)
        if field is not None:
            raise serializers.ValidationError(f'Field name "{field_name}" already exists on table "{table_name}"')

    def _validate_join_key(self, join_key: Optional[str], table: Optional[str], team_id: int) -> None:
        if not join_key:
            raise serializers.ValidationError("View column must have a join key.")

        if not table:
            raise serializers.ValidationError("View column must have a table.")

        database = create_hogql_database(team_id)
        try:
            database.get_table(table)
        except Exception:
            raise serializers.ValidationError(f"Invalid table: {table}")

        node = parse_expr(join_key)
        if not isinstance(node, Field):
            raise serializers.ValidationError(f"Join key {join_key} must be a table field - no function calls allowed")

        return

    def _validate_join_key(self, group_type_index: Optional[int], source_table: Optional[str]) -> None:
        if group_type_index is None:
            return
        if source_table != "groups":
            raise serializers.ValidationError(f"Can only specify a group_type_index when joining onto groups table")


class ViewLinkViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete View Columns.
    """

    scope_object = "INTERNAL"
    queryset = DataWarehouseJoin.objects.all()
    serializer_class = ViewLinkSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def safely_get_queryset(self, queryset):
        return queryset.exclude(deleted=True).prefetch_related("created_by").order_by(self.ordering)
