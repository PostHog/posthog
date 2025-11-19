from typing import Optional

from clickhouse_driver.errors import ServerException
from rest_framework import filters, response, serializers, status, viewsets

from posthog.hogql import ast
from posthog.hogql.ast import Call, Field
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import LazyJoin
from posthog.hogql.database.utils import get_join_field_chain
from posthog.hogql.errors import QueryError, SyntaxError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.errors import look_up_error_code_meta
from posthog.exceptions_capture import capture_exception

from products.data_warehouse.backend.models import DataWarehouseJoin


class ViewLinkValidationMixin:
    def _database(self, team_id: int) -> Database:
        database = self.context.get("database", None)  # type: ignore[attr-defined]
        if not database:
            database = Database.create_for(team_id=team_id)
        return database

    def get_table_name(self, table_name: str) -> str:
        team_id = self.context["team_id"]  # type: ignore[attr-defined]
        database = self._database(team_id)

        if not database.has_table(table_name):
            return table_name

        table = database.get_table(table_name)
        return table.to_printed_hogql().replace("`", "")

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

    def _validate_join_key(self, join_key: Optional[str], table_name: Optional[str], team_id: int) -> None:
        if not join_key:
            raise serializers.ValidationError({"non_field_errors": ["View column must have a join key."]})

        if not table_name:
            raise serializers.ValidationError({"non_field_errors": ["View column must have a table."]})

        database = self._database(team_id)

        try:
            database.get_table(table_name)
        except Exception:
            raise serializers.ValidationError({"non_field_errors": [f"Invalid table: {table_name}"]})

        try:
            node = parse_expr(join_key)
        except SyntaxError as e:
            raise serializers.ValidationError({"non_field_errors": [str(e)]})

        if not isinstance(node, Field) and not (isinstance(node, Call) and isinstance(node.args[0], Field)):
            raise serializers.ValidationError({"non_field_errors": [f"Join key {join_key} must be a table field"]})

        return


class ViewLinkSerializer(serializers.ModelSerializer, ViewLinkValidationMixin):
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

        view["source_table_name"] = self.get_table_name(instance.source_table_name)
        view["joining_table_name"] = self.get_table_name(instance.joining_table_name)

        return view

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


class ViewLinkValidationSerializer(serializers.Serializer, ViewLinkValidationMixin):
    joining_table_name = serializers.CharField(max_length=255, required=True)
    joining_table_key = serializers.CharField(max_length=255, required=True)
    source_table_name = serializers.CharField(max_length=255, required=True)
    source_table_key = serializers.CharField(max_length=255, required=True)

    def run_validation(self, data=...):
        value = super().run_validation(data=data)
        value["source_table"] = self.get_table_name(value["source_table_name"])
        value["joining_table"] = self.get_table_name(value["joining_table_name"])

        self._validate_join_key(
            join_key=value["source_table_key"],
            table_name=value["source_table_name"],
            team_id=self.context["team_id"],
        )
        self._validate_join_key(
            join_key=value["joining_table_key"],
            table_name=value["joining_table_name"],
            team_id=self.context["team_id"],
        )
        return value


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
    serializer_classes = {
        "default": ViewLinkSerializer,
        "validate": ViewLinkValidationSerializer,
    }

    def get_serializer_class(self):
        return self.serializer_classes.get(self.action, self.serializer_classes["default"])

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["database"] = Database.create_for(team_id=self.team_id)
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

    @action(methods=["POST"], detail=False)
    def validate(self, request, *args, **kwargs):
        response_data: dict[str, Optional[bool | str | list]] = {
            "is_valid": False,
            "msg": None,
            "hogql": None,
            "results": [],
        }
        status_code = status.HTTP_200_OK
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        join = DataWarehouseJoin(**request.data)
        database = serializer.context["database"]

        source_table_name = serializer.validated_data["source_table_name"]
        source_table = database.get_table(source_table_name)
        source_table_key = serializer.validated_data["source_table_key"]
        from_field = get_join_field_chain(source_table_key)

        joining_table = database.get_table(serializer.validated_data.get("joining_table_name"))
        joining_table_key = serializer.validated_data.get("joining_table_key")
        to_field = get_join_field_chain(joining_table_key)
        assert to_field is not None

        source_table.fields["validation"] = LazyJoin(
            from_field=from_field,
            to_field=to_field,
            join_table=joining_table,
            join_function=join.join_function(override_join_type="INNER JOIN"),
        )
        validation_query = parse_select(
            "SELECT {to_field} FROM {source_table_name} LIMIT 10",
            placeholders={
                "to_field": ast.Field(chain=["validation", *to_field]),
                "source_table_name": parse_expr(source_table_name),
            },
        )

        try:
            query_response = execute_hogql_query(
                query=validation_query, team=self.team, context=HogQLContext(database=database)
            )
            response_data["hogql"] = query_response.hogql
            response_data["results"] = query_response.results
            response_data["is_valid"] = True
            if len(query_response.results) == 0:
                response_data["msg"] = "Validation query returned no results"
        except ServerException as e:
            capture_exception(e)
            response_data = {
                "attr": None,
                "code": e.__class__.__name__,
                "detail": "An internal error occurred while validating.",
                "type": "query_error",
                "hogql": validation_query.to_hogql(),
            }
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR  # type: ignore[assignment]
            response_data["is_valid"] = False

            is_safe = look_up_error_code_meta(e).user_safe
            if is_safe:
                response_data["detail"] = str(e)
        except QueryError as e:
            capture_exception(e)
            response_data = {
                "attr": None,
                "code": e.__class__.__name__,
                "detail": str(e),  # QueryError inherits from ExposedHogQLError, so it is safe to show the message
                "type": "query_error",
                "hogql": validation_query.to_hogql(),
            }
            status_code = status.HTTP_400_BAD_REQUEST  # type: ignore[assignment]

        return response.Response(response_data, status=status_code)
