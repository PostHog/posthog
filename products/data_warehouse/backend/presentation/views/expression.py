from typing import Any, Optional, cast

from django.db import IntegrityError, transaction

from rest_framework import filters, response, serializers, viewsets

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.direct_connection import resolve_database_for_connection
from posthog.hogql.direct_sql import get_adapter
from posthog.hogql.errors import BaseHogQLError, ExposedHogQLError
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_and_print_ast

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.data_tools.backend.facade.models import DataWarehouseExpression


class DataWarehouseExpressionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataWarehouseExpression
        fields = [
            "id",
            "deleted",
            "created_by",
            "created_at",
            "table_name",
            "field_name",
            "expression",
            "connection_id",
        ]
        read_only_fields = ["id", "created_by", "created_at"]
        extra_kwargs = {
            "deleted": {"help_text": "Whether this expression has been soft-deleted."},
            "table_name": {"help_text": "Name of the table the expression field is added to, for example events."},
            "field_name": {
                "help_text": "Name of the virtual field the expression is exposed as. Must not clash with an existing field on the table."
            },
            "expression": {
                "help_text": "HogQL expression evaluated in the context of the table, for example properties.$browser or lower(email)."
            },
            "connection_id": {
                "help_text": "ExternalDataSource id to scope the expression to that connection's direct-query database. Null applies it to the default warehouse database."
            },
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = cast(Optional[DataWarehouseExpression], self.instance)
        table_name = attrs.get("table_name", instance.table_name if instance else None)
        field_name = attrs.get("field_name", instance.field_name if instance else None)
        expression = attrs.get("expression", instance.expression if instance else None)
        connection_id = attrs.get("connection_id", instance.connection_id if instance else None)
        team = self.context["get_team"]()
        team_id = team.pk

        if not table_name:
            raise serializers.ValidationError({"table_name": ["Table name must not be empty."]})
        if not field_name:
            raise serializers.ValidationError({"field_name": ["Field name must not be empty."]})
        if "." in field_name:
            raise serializers.ValidationError({"field_name": ["Field name must not contain a period: '.'"]})
        if not expression:
            raise serializers.ValidationError({"expression": ["Expression must not be empty."]})

        try:
            source, database = resolve_database_for_connection(
                team=team,
                connection_id=str(connection_id) if connection_id else None,
                user=cast(User, self.context["request"].user),
                error_factory=ValueError,
            )
        except Exception:
            if connection_id:
                raise serializers.ValidationError({"connection_id": ["Invalid connection."]})
            raise
        try:
            table = database.get_table(table_name)
        except Exception:
            raise serializers.ValidationError({"table_name": [f"Invalid table: {table_name}"]})

        # The field this instance already contributes to the built database is the one name it may keep.
        is_own_field = (
            instance is not None
            and not instance.deleted
            and instance.table_name == table_name
            and instance.field_name == field_name
            and instance.connection_id == connection_id
        )
        if not is_own_field and table.fields.get(field_name) is not None:
            raise serializers.ValidationError(
                {
                    "field_name": [
                        f'Field "{field_name}" already exists on table "{table_name}". Expressions can\'t override existing fields.'
                    ]
                }
            )

        duplicates = DataWarehouseExpression.objects.for_team(team_id).filter(
            table_name=table_name, field_name=field_name, connection_id=connection_id, deleted=False
        )
        if instance is not None:
            duplicates = duplicates.exclude(id=instance.id)
        if duplicates.exists():
            raise serializers.ValidationError(
                {"field_name": [f'An expression named "{field_name}" already exists on table "{table_name}".']}
            )

        try:
            expr_node = parse_expr(expression)
        except ExposedHogQLError as e:
            raise serializers.ValidationError({"expression": [str(e)]})

        # Print a probe query with the new field present on the table. Printing (unlike type
        # resolution) fully expands expression fields, so an unknown column or a recursive
        # expression fails here instead of breaking every later query against the table.
        previous_field = table.fields.get(field_name)
        table.fields[field_name] = ExpressionField(name=field_name, expr=expr_node, isolate_scope=True)
        try:
            dialect: HogQLDialect = "clickhouse"
            if source is not None:
                adapter = get_adapter(source.direct_engine)
                dialect = adapter.dialect if adapter is not None and adapter.dialect is not None else "postgres"
            context = HogQLContext(
                team_id=team_id,
                database=database,
                enable_select_queries=True,
                is_direct_query=source is not None,
            )
            probe_query = ast.SelectQuery(
                select=[ast.Field(chain=[field_name])],
                select_from=ast.JoinExpr(table=ast.Field(chain=cast(list[str | int], table_name.split(".")))),
            )
            prepare_and_print_ast(probe_query, context, dialect)
        except ExposedHogQLError as e:
            raise serializers.ValidationError({"expression": [str(e)]})
        except RecursionError:
            raise serializers.ValidationError(
                {"expression": ["Expression can't reference itself, directly or through another expression."]}
            )
        except BaseHogQLError:
            raise serializers.ValidationError(
                {"expression": [f'This expression can\'t be used on table "{table_name}".']}
            )
        finally:
            if previous_field is None:
                table.fields.pop(field_name, None)
            else:
                table.fields[field_name] = previous_field

        return attrs

    def _duplicate_error(self, field_name: str, table_name: str) -> serializers.ValidationError:
        return serializers.ValidationError(
            {"field_name": [f'An expression named "{field_name}" already exists on table "{table_name}".']}
        )

    def create(self, validated_data: dict[str, Any]) -> DataWarehouseExpression:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        try:
            # atomic() takes a savepoint so the caught IntegrityError can't poison an
            # enclosing transaction.
            with transaction.atomic():
                return DataWarehouseExpression.objects.create(**validated_data)
        except IntegrityError:
            # The unique constraints backstop the check-then-act duplicate validation above;
            # losing that race must surface as the same 400, not a 500.
            raise self._duplicate_error(validated_data["field_name"], validated_data["table_name"])

    def update(self, instance: DataWarehouseExpression, validated_data: dict[str, Any]) -> DataWarehouseExpression:
        try:
            with transaction.atomic():
                return super().update(instance, validated_data)
        except IntegrityError:
            raise self._duplicate_error(
                validated_data.get("field_name", instance.field_name),
                validated_data.get("table_name", instance.table_name),
            )


class DataWarehouseExpressionViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update and delete saved HogQL expressions that appear as virtual fields on tables.
    """

    scope_object = "warehouse_view"
    # `.unscoped()` avoids the fail-closed manager raising at import (no team context yet);
    # `safely_get_queryset` re-scopes every real query to the team.
    queryset = DataWarehouseExpression.objects.unscoped()
    serializer_class = DataWarehouseExpressionSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["field_name", "table_name"]
    ordering = "-created_at"

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).prefetch_related("created_by").order_by(self.ordering)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset().exclude(deleted=True))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)

    def perform_destroy(self, instance: DataWarehouseExpression) -> None:
        instance.soft_delete()
