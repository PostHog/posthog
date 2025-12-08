from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import pagination, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob


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

    @action(methods=["GET"], detail=False)
    def running(self, request: Request, *args, **kwargs) -> Response:
        """
        Get all currently running jobs for this team.
        Returns a list of jobs with status 'Running'.
        """
        queryset = self.safely_get_queryset().filter(status=DataModelingJob.Status.RUNNING)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
