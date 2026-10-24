from datetime import UTC, datetime, timedelta

from django.db import models

from drf_spectacular.helpers import forced_singular_serializer
from drf_spectacular.utils import OpenApiResponse
from rest_framework import response, serializers, viewsets

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.api import get_model_usage
from products.data_modeling.backend.facade.models import DataModelingJobEngine, DataWarehouseSavedQuery


class ModelUsageEngine(models.TextChoices):
    ALL = "all", "All"
    CLICKHOUSE = "clickhouse", "ClickHouse"
    MANAGED_WAREHOUSE = "managed_warehouse", "Managed warehouse"


class ModelUsageQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(
        required=False, min_value=1, max_value=90, help_text="Number of complete UTC days, up to 90."
    )
    date_from = serializers.DateField(
        required=False, help_text="Inclusive UTC start date for a custom range, up to 366 complete days."
    )
    date_to = serializers.DateField(
        required=False, help_text="Inclusive UTC end date for a custom range. Today is always excluded."
    )
    page = serializers.IntegerField(default=1, min_value=1, help_text="Model breakdown page, starting at 1.")
    page_size = serializers.IntegerField(
        default=20, min_value=1, max_value=100, help_text="Models per page, up to 100."
    )
    engine = serializers.ChoiceField(
        choices=ModelUsageEngine.choices,
        default=ModelUsageEngine.CLICKHOUSE,
        help_text="Materialization engine. All combines ClickHouse and managed warehouse usage.",
    )
    saved_query_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Limit usage to one accessible materialized view."
    )

    def validate(self, attrs: dict) -> dict:
        days = attrs.get("days")
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if days is not None and date_from is not None:
            raise serializers.ValidationError("Use days or a custom date range, not both.")
        if date_to is not None and date_from is None:
            raise serializers.ValidationError({"date_from": "A start date is required for a custom date range."})
        today = datetime.now(UTC).date()
        if date_from is None:
            end_date = today
            attrs["start_date"] = end_date - timedelta(days=days or 30)
            attrs["end_date"] = end_date
            return attrs

        exclusive_date_to = min(date_to, today - timedelta(days=1)) + timedelta(days=1) if date_to else today
        if date_from >= exclusive_date_to:
            raise serializers.ValidationError({"date_from": "The range must include at least one complete UTC day."})
        if (exclusive_date_to - date_from).days > 366:
            raise serializers.ValidationError({"date_from": "The custom date range cannot exceed 366 days."})
        attrs["start_date"] = date_from
        attrs["end_date"] = exclusive_date_to
        return attrs


class ModelUsageTotalsSerializer(serializers.Serializer):
    runs = serializers.IntegerField(help_text="Finished materialization runs, including failures and cancellations.")
    measured_runs = serializers.IntegerField(help_text="Runs with recorded usage. Other runs have unknown cost.")
    read_bytes = serializers.IntegerField(
        allow_null=True, help_text="Measured bytes read, including probes and retries. Null if unmeasured."
    )
    read_rows = serializers.IntegerField(allow_null=True, help_text="Measured rows read. Null if unmeasured.")
    cpu_microseconds = serializers.IntegerField(
        allow_null=True, help_text="Measured CPU microseconds. Null if unmeasured."
    )
    query_count = serializers.IntegerField(
        allow_null=True, help_text="Measured ClickHouse query count. Null if unmeasured."
    )


class ModelUsageEngineSerializer(ModelUsageTotalsSerializer):
    engine = serializers.CharField(help_text="Materialization engine: clickhouse or managed_warehouse.")


class ModelUsageDaySerializer(ModelUsageTotalsSerializer):
    day = serializers.DateField(help_text="UTC day on which the runs finished.")
    engines = ModelUsageEngineSerializer(many=True, help_text="Usage totals for each selected engine.")


class ModelUsageRowSerializer(ModelUsageTotalsSerializer):
    saved_query_id = serializers.UUIDField(allow_null=True, help_text="Model ID, or null if permanently deleted.")
    name = serializers.CharField(help_text="Model name.")
    deleted = serializers.BooleanField(help_text="Whether this model has been deleted.")
    engines = ModelUsageEngineSerializer(many=True, help_text="Usage totals for each selected engine.")


class ModelUsageSerializer(serializers.Serializer):
    date_from = serializers.DateField(help_text="Inclusive UTC start date.")
    date_to = serializers.DateField(help_text="Exclusive UTC end date. Today's incomplete usage is excluded.")
    overview = ModelUsageTotalsSerializer(help_text="Totals over the whole date range.")
    trends = ModelUsageDaySerializer(many=True, help_text="Daily usage, attributed to when each run finished.")
    models = ModelUsageRowSerializer(many=True, help_text="Model breakdown, highest measured bytes first.")
    count = serializers.IntegerField(help_text="Total number of models in the breakdown.")
    usage_updated_at = serializers.DateTimeField(
        allow_null=True, help_text="Latest usage collection timestamp in this range."
    )


class ModelUsageViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "warehouse_view"
    serializer_class = ModelUsageSerializer
    queryset = DataWarehouseSavedQuery.objects.all()
    pagination_class = None

    @validated_request(
        query_serializer=ModelUsageQuerySerializer,
        responses={200: OpenApiResponse(response=forced_singular_serializer(ModelUsageSerializer))},
    )
    def list(self, request: ValidatedRequest, **kwargs: object) -> response.Response:
        query_data = request.validated_query_data
        saved_queries = self.get_queryset()
        if saved_query_id := query_data.get("saved_query_id"):
            saved_queries = saved_queries.filter(id=saved_query_id)
        selected_engine = query_data["engine"]
        engines = (
            (DataModelingJobEngine.CLICKHOUSE, DataModelingJobEngine.MANAGED_WAREHOUSE)
            if selected_engine == ModelUsageEngine.ALL
            else (DataModelingJobEngine(selected_engine),)
        )
        return response.Response(
            ModelUsageSerializer(
                get_model_usage(
                    self.team_id,
                    saved_query_ids=list(saved_queries.values_list("id", flat=True)),
                    page=query_data["page"],
                    page_size=query_data["page_size"],
                    start_date=query_data["start_date"],
                    end_date=query_data["end_date"],
                    engines=engines,
                )
            ).data
        )
