from typing import Any

import structlog
from django.conf import settings
from django.db import transaction
from rest_framework import exceptions, filters, request, response, serializers, status, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import SerializedField, create_hogql_database, serialize_fields
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.metadata import is_valid_view
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.warehouse.models import DataWarehouseJoin, DataWarehouseModelPath, DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


class DataWarehouseSavedQuerySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    columns = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DataWarehouseSavedQuery
        fields = [
            "id",
            "deleted",
            "name",
            "query",
            "created_by",
            "created_at",
            "columns",
        ]
        read_only_fields = ["id", "created_by", "created_at", "columns"]

    def get_columns(self, view: DataWarehouseSavedQuery) -> list[SerializedField]:
        team_id = self.context["team_id"]
        context = HogQLContext(team_id=team_id, database=create_hogql_database(team_id=team_id))

        fields = serialize_fields(view.hogql_definition().fields, context, view.name, table_type="external")
        return [
            SerializedField(
                key=field.name,
                name=field.name,
                type=field.type,
                schema_valid=field.schema_valid,
                fields=field.fields,
                table=field.table,
                chain=field.chain,
            )
            for field in fields
        ]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        view = DataWarehouseSavedQuery(**validated_data)
        # The columns will be inferred from the query
        try:
            view.columns = view.get_columns()
            view.external_tables = view.s3_tables
        except Exception as err:
            raise serializers.ValidationError(str(err))

        with transaction.atomic():
            view.save()

            try:
                DataWarehouseModelPath.objects.create_from_saved_query(view)
            except Exception:
                # For now, do not fail saved query creation if we cannot model-ize it.
                # Later, after bugs and errors have been ironed out, we may tie these two
                # closer together.
                logger.exception("Failed to create model path when creating view %s", view.name)

        return view

    def update(self, instance: Any, validated_data: Any) -> Any:
        view: DataWarehouseSavedQuery = super().update(instance, validated_data)

        try:
            view.columns = view.get_columns()
            view.external_tables = view.s3_tables
        except Exception as err:
            raise serializers.ValidationError(str(err))

        with transaction.atomic():
            view.save()

            try:
                DataWarehouseModelPath.objects.create_from_saved_query(view)
            except Exception:
                logger.exception("Failed to update model path when updating view %s", view.name)

        return view

    def validate_query(self, query):
        team_id = self.context["team_id"]

        context = HogQLContext(team_id=team_id, enable_select_queries=True)
        select_ast = parse_select(query["query"])
        _is_valid_view = is_valid_view(select_ast)
        if not _is_valid_view:
            raise exceptions.ValidationError(detail="Ensure all fields are aliased")

        try:
            print_ast(
                node=select_ast,
                context=context,
                dialect="clickhouse",
                stack=None,
                settings=None,
            )
        except Exception as err:
            if isinstance(err, ExposedHogQLError):
                error = str(err)
                raise exceptions.ValidationError(detail=f"Invalid query: {error}")
            elif not settings.DEBUG:
                # We don't want to accidentally expose too much data via errors
                raise exceptions.ValidationError(detail=f"Unexpected {err.__class__.__name__}")

        return query


class DataWarehouseSavedQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Tables.
    """

    scope_object = "INTERNAL"
    queryset = DataWarehouseSavedQuery.objects.all()
    serializer_class = DataWarehouseSavedQuerySerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def safely_get_queryset(self, queryset):
        return queryset.prefetch_related("created_by").exclude(deleted=True).order_by(self.ordering)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        instance: DataWarehouseSavedQuery = self.get_object()
        DataWarehouseJoin.objects.filter(source_table_name=instance.name).delete()
        DataWarehouseJoin.objects.filter(joining_table_name=instance.name).delete()
        self.perform_destroy(instance)

        return response.Response(status=status.HTTP_204_NO_CONTENT)
