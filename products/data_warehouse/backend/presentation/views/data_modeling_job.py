from django.db.models import Q

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import pagination, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.ph_client import feature_enabled_or_false

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine

DUCKGRES_SHADOW_FLAG = "duckgres-data-modeling-shadow"


class DataModelingJobSerializer(serializers.ModelSerializer):
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

    class Meta:
        model = DataModelingJob
        fields = [
            "id",
            "saved_query_id",
            "status",
            "run_mode",
            "rows_materialized",
            "error",
            "created_at",
            "last_run_at",
            "updated_at",
            "workflow_id",
            "workflow_run_id",
            "rows_expected",
        ]
        read_only_fields = fields


class DataModelingJobPagination(pagination.LimitOffsetPagination):
    default_limit = 10
    max_limit = 100


class DataModelingJobViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    List data modeling jobs which are "runs" for our saved queries.
    """

    scope_object = "warehouse_view"
    serializer_class = DataModelingJobSerializer
    pagination_class = DataModelingJobPagination
    queryset = DataModelingJob.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["saved_query_id"]
    search_fields = ["saved_query_id"]
    ordering_fields = ["created_at"]
    ordering = "-created_at"

    def _is_duckgres_shadow_enabled(self) -> bool:
        try:
            return feature_enabled_or_false(
                DUCKGRES_SHADOW_FLAG,
                str(self.team.pk),
                groups={
                    "organization": str(self.team.organization_id),
                    "project": str(self.team.id),
                },
                group_properties={
                    "organization": {"id": str(self.team.organization_id)},
                    "project": {"id": str(self.team.id)},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        except Exception:
            return False

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team_id=self.team_id)
        if not self._is_duckgres_shadow_enabled():
            qs = qs.exclude(engine=DataModelingJobEngine.DUCKGRES)
        return qs.order_by("-created_at")

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
