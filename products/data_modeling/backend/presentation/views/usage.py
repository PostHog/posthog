from drf_spectacular.helpers import forced_singular_serializer
from drf_spectacular.utils import OpenApiResponse
from rest_framework import response, serializers, viewsets

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.api import get_model_usage
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


class ModelUsageQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(
        default=30, min_value=1, max_value=90, help_text="Number of complete UTC days, up to 90."
    )
    page = serializers.IntegerField(default=1, min_value=1, help_text="Model breakdown page, starting at 1.")
    page_size = serializers.IntegerField(
        default=20, min_value=1, max_value=100, help_text="Models per page, up to 100."
    )
    engine = serializers.ChoiceField(
        choices=["all", "clickhouse", "managed_warehouse"],
        default="clickhouse",
        help_text="Materialization engine. All combines ClickHouse and managed warehouse usage.",
    )
    saved_query_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Limit usage to one accessible materialized view."
    )


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
        query_data = {**request.validated_query_data}
        saved_queries = self.get_queryset()
        if saved_query_id := query_data.pop("saved_query_id", None):
            saved_queries = saved_queries.filter(id=saved_query_id)
        return response.Response(
            ModelUsageSerializer(
                get_model_usage(
                    self.team_id,
                    saved_query_ids=list(saved_queries.values_list("id", flat=True)),
                    **query_data,
                )
            ).data
        )
