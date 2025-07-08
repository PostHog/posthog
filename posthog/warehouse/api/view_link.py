from typing import Optional

from rest_framework import filters, serializers, viewsets, response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.hogql.ast import Field, Call
from posthog.hogql.database.database import create_hogql_database, Database
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
            "configuration",
        ]
        read_only_fields = ["id", "created_by", "created_at"]

    def to_representation(self, instance):
        view = super().to_representation(instance)

        view["source_table_name"] = self.get_source_table_name(instance)
        view["joining_table_name"] = self.get_joining_table_name(instance)

        return view

    def _database(self, team_id: int) -> Database:
        database = self.context.get("database", None)
        if not database:
            database = create_hogql_database(team_id=team_id)
        return database

    def get_source_table_name(self, join: DataWarehouseJoin) -> str:
        team_id = self.context["team_id"]

        database = self._database(team_id)

        if not database.has_table(join.source_table_name):
            return join.source_table_name

        table = database.get_table(join.source_table_name)

        return table.to_printed_hogql().replace("`", "")

    def get_joining_table_name(self, join: DataWarehouseJoin) -> str:
        team_id = self.context["team_id"]

        database = self._database(team_id)

        if not database.has_table(join.joining_table_name):
            return join.joining_table_name

        table = database.get_table(join.joining_table_name)

        return table.to_printed_hogql().replace("`", "")

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

        view_link = DataWarehouseJoin.objects.create(**validated_data)

        return view_link

    def _validate_key_uniqueness(self, field_name: str, table_name: str, team_id: int) -> None:
        if field_name is None:
            raise serializers.ValidationError("Field name must not be empty.")

        if "." in field_name:
            raise serializers.ValidationError("Field name must not contain a period: '.'")

        database = self._database(team_id)

        table = database.get_table(table_name)
        field = table.fields.get(field_name)
        if field is not None:
            raise serializers.ValidationError(f'Field name "{field_name}" already exists on table "{table_name}"')

    def _validate_join_key(self, join_key: Optional[str], table: Optional[str], team_id: int) -> None:
        if not join_key:
            raise serializers.ValidationError("View column must have a join key.")

        if not table:
            raise serializers.ValidationError("View column must have a table.")

        database = self._database(team_id)

        try:
            database.get_table(table)
        except Exception:
            raise serializers.ValidationError(f"Invalid table: {table}")

        node = parse_expr(join_key)
        if not isinstance(node, Field) and not (isinstance(node, Call) and isinstance(node.args[0], Field)):
            raise serializers.ValidationError(f"Join key {join_key} must be a table field")

        return


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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["database"] = create_hogql_database(team_id=self.team_id)
        return context

    def safely_get_queryset(self, queryset):
        return queryset.prefetch_related("created_by").order_by(self.ordering)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset().exclude(deleted=True))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)
