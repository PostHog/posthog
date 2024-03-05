from typing import Any, List

from django.conf import settings
from rest_framework import exceptions, filters, serializers, viewsets
from rest_framework.exceptions import NotAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import SerializedField, serialize_fields
from posthog.hogql.errors import HogQLException
from posthog.hogql.metadata import is_valid_view
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.models import User
from posthog.warehouse.models import DataWarehouseSavedQuery


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

    def get_columns(self, view: DataWarehouseSavedQuery) -> List[SerializedField]:
        return serialize_fields(view.hogql_definition().fields)

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

        view.save()
        return view

    def update(self, instance: Any, validated_data: Any) -> Any:
        view: DataWarehouseSavedQuery = super().update(instance, validated_data)

        try:
            view.columns = view.get_columns()
            view.external_tables = view.s3_tables
        except Exception as err:
            raise serializers.ValidationError(str(err))
        view.save()
        return view

    def validate_query(self, query):
        team_id = self.context["team_id"]

        context = HogQLContext(team_id=team_id, enable_select_queries=True)
        context.max_view_depth = 0
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
            if isinstance(err, ValueError) or isinstance(err, HogQLException):
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
