from typing import Optional, cast

from clickhouse_driver.errors import ServerException
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import filters, response, serializers, status, viewsets

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.lazy_join_tags import DATA_WAREHOUSE
from posthog.hogql.database.models import LazyJoin
from posthog.hogql.database.utils import get_join_field_chain
from posthog.hogql.database.warehouse_join_resolvers import data_warehouse_resolver_params
from posthog.hogql.errors import QueryError, SyntaxError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import look_up_clickhouse_error_code_meta
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.data_tools.backend.facade.models import DataWarehouseJoin

MATCH_RATE_SAMPLE_SIZE = 10_000
PREVIEW_SCAN_ROWS = 1000
PREVIEW_DISTINCT_PAIRS = 5
# The match-rate stats query tests each sampled source key against the joining table's key column,
# which reads that column in full. Cap its execution so this best-effort scan can't tie up warehouse
# query capacity; over-limit runs raise and fall back to null stats rather than sampling the joining
# side, which would silently corrupt the match rate.
MATCH_RATE_MAX_EXECUTION_TIME = 30


class ViewLinkValidationMixin:
    def _database(self, team_id: int) -> Database:
        database = self.context.get("database", None)  # type: ignore[attr-defined]
        if not database:
            database = Database.create_for(
                team_id=team_id,
                user=cast(User, self.context["request"].user),  # type: ignore[attr-defined]
            )
            # Cache on the shared context so a list response builds the database at most
            # once instead of once per serialized row.
            self.context["database"] = database  # type: ignore[attr-defined]
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
            parse_expr(join_key)
        except SyntaxError as e:
            raise serializers.ValidationError({"non_field_errors": [str(e)]})

        if get_join_field_chain(join_key) is None:
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
        extra_kwargs = {
            "deleted": {"help_text": "Whether this join has been soft-deleted."},
            "source_table_name": {"help_text": "Name of the table the join starts from, for example events."},
            "source_table_key": {"help_text": "Column or HogQL expression on the source table used as the join key."},
            "joining_table_name": {"help_text": "Name of the table or view being joined onto the source table."},
            "joining_table_key": {"help_text": "Column or HogQL expression on the joining table used as the join key."},
            "field_name": {
                "help_text": "Accessor added to the source table to reach the joined rows, for example person in events.person."
            },
            "configuration": {"help_text": "Optional join configuration, for example experiments optimization flags."},
        }

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
        self._validate_key_uniqueness(
            field_name=field_name,
            table_name=source_table,
            team_id=self.context["team_id"],
        )

        view_link = DataWarehouseJoin.objects.create(**validated_data)

        return view_link


class ViewLinkValidationSerializer(serializers.Serializer, ViewLinkValidationMixin):
    joining_table_name = serializers.CharField(
        max_length=255, required=True, help_text="Name of the table or view being joined onto the source table."
    )
    joining_table_key = serializers.CharField(
        max_length=255, required=True, help_text="Column or HogQL expression on the joining table used as the join key."
    )
    source_table_name = serializers.CharField(
        max_length=255, required=True, help_text="Name of the table the join starts from, for example events."
    )
    source_table_key = serializers.CharField(
        max_length=255, required=True, help_text="Column or HogQL expression on the source table used as the join key."
    )

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


@extend_schema_field({"type": "array", "items": {}})
class JoinSampleRowField(serializers.JSONField):
    pass


class ViewLinkValidationResponseSerializer(serializers.Serializer):
    # The response key is the existing API contract; the DRF metaclass pops declared
    # fields off the class, so the is_valid() method is not shadowed at runtime.
    is_valid = serializers.BooleanField(  # type: ignore[assignment]
        help_text="Whether the join compiled and returned rows when executed against a sample of the source table."
    )
    msg = serializers.CharField(
        allow_null=True,
        help_text="Warning about the validation result, for example when the sampled join returned no rows.",
    )
    hogql = serializers.CharField(allow_null=True, help_text="The HogQL statement used to validate the join.")
    columns = serializers.ListField(child=serializers.CharField(), help_text="Column names for each row in results.")
    results = serializers.ListField(
        child=JoinSampleRowField(),
        help_text=f"Distinct source and joining key pairs from the joined result, at most {PREVIEW_DISTINCT_PAIRS}.",
    )
    total_rows = serializers.IntegerField(
        allow_null=True,
        help_text=f"Number of sampled source rows checked for a join match, at most {MATCH_RATE_SAMPLE_SIZE}. Null when the match-rate query failed.",
    )
    matched_rows = serializers.IntegerField(
        allow_null=True,
        help_text="Number of sampled source rows with at least one match in the joining table. Null when the match-rate query failed.",
    )
    match_rate = serializers.FloatField(
        allow_null=True,
        help_text="matched_rows divided by total_rows, between 0 and 1. Null when the match-rate query failed or no rows were sampled.",
    )


class ViewLinkValidationErrorSerializer(serializers.Serializer):
    attr = serializers.CharField(allow_null=True, help_text="Request field the error relates to, if any.")
    code = serializers.CharField(help_text="Machine-readable error code, for example QueryError.")
    detail = serializers.CharField(help_text="Why the join failed to validate.")
    type = serializers.CharField(help_text="Error category; always query_error for validation failures.")
    hogql = serializers.CharField(allow_null=True, help_text="The HogQL statement that failed to validate.")


def _join_match_stats(
    team: Team, database: Database, user: User, validated_data: dict[str, str]
) -> tuple[Optional[int], Optional[int], Optional[float]]:
    try:
        stats_query = parse_select(
            "SELECT count() AS total, countIf(k IN (SELECT {joining_key} FROM {joining_table})) AS matched "
            "FROM (SELECT {source_key} AS k FROM {source_table} LIMIT {sample_size})",
            placeholders={
                "joining_key": parse_expr(validated_data["joining_table_key"]),
                "joining_table": parse_expr(validated_data["joining_table_name"]),
                "source_key": parse_expr(validated_data["source_table_key"]),
                "source_table": parse_expr(validated_data["source_table_name"]),
                "sample_size": ast.Constant(value=MATCH_RATE_SAMPLE_SIZE),
            },
        )
        stats_response = execute_hogql_query(
            query=stats_query,
            team=team,
            context=HogQLContext(database=database, user=user),
            settings=HogQLGlobalSettings(max_execution_time=MATCH_RATE_MAX_EXECUTION_TIME),
        )
        total, matched = stats_response.results[0]
        total_rows, matched_rows = int(total), int(matched)
    except Exception as e:
        # Match stats are best-effort: a failed or too-expensive stats query must never
        # turn a valid join into a validation failure.
        capture_exception(e)
        return None, None, None
    return total_rows, matched_rows, matched_rows / total_rows if total_rows else None


class ViewLinkViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete View Columns.
    """

    scope_object = "warehouse_view"
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

    @extend_schema(
        request=ViewLinkValidationSerializer,
        responses={
            200: ViewLinkValidationResponseSerializer,
            400: OpenApiResponse(
                response=ViewLinkValidationErrorSerializer,
                description="The join does not compile or reference valid fields.",
            ),
            500: OpenApiResponse(
                response=ViewLinkValidationErrorSerializer,
                description="Validation failed with an internal query error.",
            ),
        },
    )
    @action(methods=["POST"], detail=False)
    def validate(self, request, *args, **kwargs):
        response_data: dict[str, Optional[bool | str | list | int | float]] = {
            "is_valid": False,
            "msg": None,
            "hogql": None,
            "columns": [],
            "results": [],
            "total_rows": None,
            "matched_rows": None,
            "match_rate": None,
        }
        status_code = status.HTTP_200_OK
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        join = DataWarehouseJoin(**request.data)
        # is_valid() builds and caches the database via the serializer's lazy fallback;
        # fall back to an explicit build to stay correct if that ever stops happening.
        database = serializer.context.get("database") or Database.create_for(
            team_id=self.team_id, user=cast(User, request.user)
        )

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
            resolver=DATA_WAREHOUSE,
            resolver_params=data_warehouse_resolver_params(
                source_table_key=join.source_table_key,
                joining_table_key=join.joining_table_key,
                joining_table_name=join.joining_table_name,
                configuration=join.configuration,
                override_join_type="INNER JOIN",
            ),
        )
        # DISTINCT over an unbounded scan would keep reading until it finds enough
        # distinct pairs, so the inner LIMIT caps the scan first and DISTINCT dedupes
        # only within that bounded sample.
        validation_query = parse_select(
            "SELECT DISTINCT source_key, joining_key FROM "
            "(SELECT {source_key} AS source_key, {to_field} AS joining_key "
            "FROM {source_table_name} LIMIT {scan_rows}) LIMIT {distinct_pairs}",
            placeholders={
                "source_key": parse_expr(source_table_key),
                "to_field": ast.Field(chain=["validation", *to_field]),
                "source_table_name": parse_expr(source_table_name),
                "scan_rows": ast.Constant(value=PREVIEW_SCAN_ROWS),
                "distinct_pairs": ast.Constant(value=PREVIEW_DISTINCT_PAIRS),
            },
        )

        try:
            user = cast(User, self.request.user)
            tag_queries(product=Product.WAREHOUSE, feature=Feature.QUERY)
            query_response = execute_hogql_query(
                query=validation_query,
                team=self.team,
                context=HogQLContext(database=database, user=user),
            )
            response_data["hogql"] = query_response.hogql
            response_data["columns"] = query_response.columns
            response_data["results"] = query_response.results
            response_data["is_valid"] = True
            if len(query_response.results) == 0:
                response_data["msg"] = "Validation query returned no results"
            total_rows, matched_rows, match_rate = _join_match_stats(
                team=self.team,
                database=database,
                user=cast(User, request.user),
                validated_data=serializer.validated_data,
            )
            response_data["total_rows"] = total_rows
            response_data["matched_rows"] = matched_rows
            response_data["match_rate"] = match_rate
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

            is_safe = look_up_clickhouse_error_code_meta(e).user_safe
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
