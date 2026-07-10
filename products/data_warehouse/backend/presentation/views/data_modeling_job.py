from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import pagination, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.ph_client import feature_enabled_or_false

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine

DUCKGRES_SHADOW_FLAG = "duckgres-data-modeling-shadow"


class DataModelingJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataModelingJob
        fields = [
            "id",
            "saved_query_id",
            "status",
            "rows_materialized",
            "error",
            "created_at",
            "last_run_at",
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
            .filter(saved_query_id__isnull=False, workflow_id__startswith="materialize")
            .order_by("saved_query_id", "-created_at")
            .distinct("saved_query_id")
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
