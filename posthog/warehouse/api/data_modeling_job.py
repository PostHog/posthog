from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import pagination, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.warehouse.models.data_modeling_job import DataModelingJob


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


class DataModelingJobPagination(pagination.CursorPagination):
    ordering = "-created_at"
    page_size_query_param = "limit"


class DataModelingJobViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    List data modeling jobs which are "runs" for our saved queries.
    """

    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]
    serializer_class = DataModelingJobSerializer
    pagination_class = DataModelingJobPagination
    queryset = DataModelingJob.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["saved_query_id"]
    search_fields = ["saved_query_id"]
    ordering_fields = ["created_at"]
    ordering = "-created_at"

    def safely_get_queryset(self, queryset=None):
        queryset = super().safely_get_queryset(queryset).filter(team_id=self.team_id)
        return queryset
