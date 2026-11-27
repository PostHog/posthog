from typing import Any

from django.db.models import Q, QuerySet

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.pagination import CappedCountLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import is_service_auth

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine, DataWarehouseSavedQuery


class DataModelingJobSerializer(serializers.ModelSerializer):
    saved_query_name = serializers.CharField(
        source="saved_query.name",
        read_only=True,
        allow_null=True,
        help_text="Model name, or null if permanently deleted.",
    )
    saved_query_deleted = serializers.BooleanField(
        source="saved_query.deleted",
        read_only=True,
        allow_null=True,
        help_text="Whether the model is soft-deleted, or null if permanently deleted.",
    )
    engine = serializers.CharField(read_only=True, help_text="The engine that ran this materialization job.")
    read_bytes = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Bytes read by this run, or null if it has not been measured yet.",
    )
    updated_at = serializers.DateTimeField(
        read_only=True,
        help_text="When the job row last changed. For finished jobs this is when the run reached its terminal status.",
    )
    run_mode = serializers.ChoiceField(
        choices=DataModelingJob.RunMode.choices,
        read_only=True,
        allow_null=True,
        help_text="What this run wrote: full_refresh rebuilt the whole table, so rows_materialized "
        "is the table's size; incremental wrote only its window, so rows_materialized counts just "
        "the rows synced. Null for runs from before modes were recorded, or that failed before "
        "the plan resolved.",
    )
    full_refresh_reason = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Why this run rebuilt the whole table instead of updating only new rows, for "
        "example first run, definition changed, or table missing. Null when the run was incremental.",
    )

    class Meta:
        model = DataModelingJob
        fields = [
            "id",
            "saved_query_id",
            "saved_query_name",
            "saved_query_deleted",
            "status",
            "engine",
            "run_mode",
            "full_refresh_reason",
            "rows_materialized",
            "error",
            "created_at",
            "last_run_at",
            "updated_at",
            "workflow_id",
            "workflow_run_id",
            "rows_expected",
            "read_bytes",
            "read_rows",
            "cpu_microseconds",
            "query_count",
            "usage_updated_at",
        ]
        read_only_fields = fields


class DataModelingJobPagination(CappedCountLimitOffsetPagination):
    default_limit = 10
    max_limit = 100
    count_cap = 1000

    def paginate_queryset(self, queryset: Any, request: Request, view: Any = None) -> list[Any] | None:
        jobs_counted = queryset.order_by()[: self.count_cap + 1].count()
        self.set_count(min(jobs_counted, self.count_cap), is_capped=jobs_counted > self.count_cap)
        offset = self.get_offset(request)
        limit = self.get_limit(request) or self.default_limit
        return super().paginate_queryset(queryset[offset : offset + limit], request, view)


class UUIDInFilter(django_filters.BaseInFilter, django_filters.UUIDFilter):
    pass


DATA_MODELING_JOB_LIST_FIELDS = (
    "id",
    "saved_query_id",
    "status",
    "engine",
    "run_mode",
    "full_refresh_reason",
    "rows_materialized",
    "error",
    "created_at",
    "last_run_at",
    "updated_at",
    "workflow_id",
    "workflow_run_id",
    "rows_expected",
    "read_bytes",
    "read_rows",
    "cpu_microseconds",
    "query_count",
    "usage_updated_at",
)


class DataModelingJobFilterSet(django_filters.FilterSet):
    saved_query_ids = UUIDInFilter(
        field_name="saved_query_id",
        lookup_expr="in",
        help_text="Comma-separated materialized view IDs.",
    )
    after = django_filters.IsoDateTimeFilter(
        field_name="last_run_at", lookup_expr="gte", help_text="Include jobs finished at or after this time."
    )
    before = django_filters.IsoDateTimeFilter(
        field_name="last_run_at", lookup_expr="lt", help_text="Include jobs finished before this time."
    )

    class Meta:
        model = DataModelingJob
        fields = ["saved_query_id", "saved_query_ids", "status", "engine"]


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="all_engines",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Include jobs from every materialization engine. Defaults to ClickHouse jobs only.",
            )
        ]
    )
)
class DataModelingJobViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    List data modeling jobs which are "runs" for our saved queries.
    """

    scope_object = "warehouse_view"
    serializer_class = DataModelingJobSerializer
    pagination_class = DataModelingJobPagination
    queryset = DataModelingJob.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = DataModelingJobFilterSet
    search_fields = ["saved_query_id"]
    ordering_fields = ["created_at"]
    ordering = "-created_at"

    def safely_get_queryset(self, queryset: QuerySet[DataModelingJob]) -> QuerySet[DataModelingJob]:
        all_engines = serializers.BooleanField(required=False, default=False).run_validation(
            self.request.query_params.get("all_engines", False)
        )
        queryset = queryset.filter(team_id=self.team_id)
        if not all_engines:
            queryset = queryset.filter(engine=DataModelingJobEngine.CLICKHOUSE)

        if not is_service_auth(self.request):
            queryset = queryset.filter(self._readable_saved_query_filter())

        return (
            queryset.select_related("saved_query")
            .only(
                *DATA_MODELING_JOB_LIST_FIELDS,
                "saved_query__name",
                "saved_query__deleted",
            )
            .order_by("-created_at")
        )

    def _readable_saved_query_filter(self) -> Q:
        access = self.user_access_control.list_access_filter("warehouse_view")
        if access is None or not (access.only_allowed or access.blocked_ids):
            return Q(saved_query_id__isnull=False)
        readable_saved_queries = self.user_access_control.filter_queryset_by_access_level(
            DataWarehouseSavedQuery.objects.filter(team_id=self.team_id), resource="warehouse_view"
        )
        return Q(saved_query_id__in=readable_saved_queries.values("id"))

    @action(methods=["GET"], detail=False)
    def running(self, request, *args, **kwargs):
        """Get all currently running jobs from the v2 backend."""
        queryset = self.get_queryset().filter(
            status=DataModelingJob.Status.RUNNING,
            workflow_id__startswith="materialize",
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(methods=["GET"], detail=False)
    def recent(self, request, *args, **kwargs):
        """Get the most recent non-running job for each saved query from the v2 backend."""
        queryset = (
            self.get_queryset()
            .exclude(status=DataModelingJob.Status.RUNNING)
            .filter(saved_query_id__isnull=False)
            # a skip row is written by the DAG run itself, so it carries the execute-dag id rather
            # than a materialize one. Matching only materialize hides the skip and leaves the last
            # successful run standing as "last run" for as long as the upstream stays broken.
            .filter(Q(workflow_id__startswith="materialize") | Q(workflow_id__startswith="execute-dag"))
            .order_by("saved_query_id", "-created_at")
            .distinct("saved_query_id")
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
