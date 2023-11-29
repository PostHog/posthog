import uuid
from typing import Any

import structlog
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import User
from posthog.permissions import OrganizationMemberPermissions
from posthog.warehouse.data_load.service import (
    sync_external_data_job_workflow,
    trigger_external_data_workflow,
    delete_external_data_workflow,
)
from posthog.warehouse.models import ExternalDataJob, ExternalDataSource

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
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            status="running",
            source_type="Stripe",
            job_inputs={
                "stripe_secret_key": client_secret,
            },
        )

        sync_external_data_job_workflow(new_source_model, create=True)

        return Response(status=status.HTTP_201_CREATED, data={"source_id": new_source_model.source_id})

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        delete_external_data_workflow(instance)
        return super().destroy(request, *args, **kwargs)

    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance = self.get_object()
        trigger_external_data_workflow(instance)
        return Response(status=status.HTTP_200_OK)
