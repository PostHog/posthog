from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import ExternalDataSource, ExternalDataJob
from posthog.warehouse.external_data_source.source import delete_source
from posthog.warehouse.external_data_source.destination import delete_destination
from posthog.warehouse.data_load.service import start_external_data_job_workflow, ExternalDataJobInputs
from posthog.api.routing import StructuredViewSetMixin
from rest_framework.decorators import action
import uuid

from posthog.temporal.client import sync_connect

from posthog.models import User
from typing import Any
import structlog

logger = structlog.get_logger(__name__)


class ExternalDataSourceSerializers(serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)
    status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ExternalDataSource
        fields = ["id", "source_id", "created_at", "created_by", "status", "client_secret", "account_id", "source_type"]
        read_only_fields = ["id", "source_id", "created_by", "created_at", "status", "source_type"]

    # TODO: temporary just to test
    def get_status(self, instance: ExternalDataSource) -> str:
        job = ExternalDataJob.objects.filter(pipeline_id=instance.id).order_by("-created_at").first()
        if job:
            return job.status

        return instance.status


class ExternalDataSourceViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete External data Sources.
    """

    queryset = ExternalDataSource.objects.all()
    serializer_class = ExternalDataSourceSerializers
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ["source_id"]
    ordering = "-created_at"

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        if self.action == "list":
            return self.queryset.filter(team_id=self.team_id).prefetch_related("created_by").order_by(self.ordering)

        return self.queryset.filter(team_id=self.team_id).prefetch_related("created_by").order_by(self.ordering)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        client_secret = request.data["client_secret"]

        # TODO: remove dummy vars
        new_source_model = ExternalDataSource.objects.create(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=self.team,
            status="running",
            source_type="Stripe",
            job_inputs={
                "stripe_secret_key": client_secret,
            },
        )

        inputs = ExternalDataJobInputs(
            team_id=self.team_id,
            external_data_source_id=new_source_model.pk,
        )

        temporal = sync_connect()
        start_external_data_job_workflow(temporal, inputs)

        return Response(status=status.HTTP_201_CREATED, data={"source_id": new_source_model.source_id})

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        try:
            delete_source(instance.source_id)
        except Exception as e:
            logger.exception(
                f"Data Warehouse: Failed to delete source with id: {instance.source_id}",
                exc_info=e,
            )

        try:
            delete_destination(instance.destination_id)
        except Exception as e:
            logger.exception(
                f"Data Warehouse: Failed to delete destination with id: {instance.destination_id}",
                exc_info=e,
            )

        return super().destroy(request, *args, **kwargs)

    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance = self.get_object()
        # TODO: trigger external data job workflow
        return Response(status=status.HTTP_200_OK)
