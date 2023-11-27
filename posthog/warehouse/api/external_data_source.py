from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import ExternalDataSource
from posthog.warehouse.external_data_source.workspace import get_or_create_workspace
from posthog.warehouse.external_data_source.source import StripeSourcePayload, create_stripe_source, delete_source
from posthog.warehouse.external_data_source.connection import create_connection, start_sync
from posthog.warehouse.external_data_source.destination import create_destination, delete_destination
from posthog.tasks.warehouse import sync_resource
from posthog.api.routing import StructuredViewSetMixin
from rest_framework.decorators import action

from posthog.models import User
from typing import Any
import structlog

logger = structlog.get_logger(__name__)


class ExternalDataSourceSerializers(serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)

    class Meta:
        model = ExternalDataSource
        fields = ["id", "source_id", "created_at", "created_by", "status", "client_secret", "account_id", "source_type"]
        read_only_fields = ["id", "source_id", "created_by", "created_at", "status", "source_type"]


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
        account_id = request.data["account_id"]
        client_secret = request.data["client_secret"]

        workspace_id = get_or_create_workspace(self.team_id)

        stripe_payload = StripeSourcePayload(
            account_id=account_id,
            client_secret=client_secret,
        )
        new_source = create_stripe_source(stripe_payload, workspace_id)

        try:
            new_destination = create_destination(self.team_id, workspace_id)
        except Exception as e:
            delete_source(new_source.source_id)
            raise e

        try:
            new_connection = create_connection(new_source.source_id, new_destination.destination_id)
        except Exception as e:
            delete_source(new_source.source_id)
            delete_destination(new_destination.destination_id)
            raise e

        ExternalDataSource.objects.create(
            source_id=new_source.source_id,
            connection_id=new_connection.connection_id,
            destination_id=new_destination.destination_id,
            team=self.team,
            status="running",
            source_type="Stripe",
        )

        start_sync(new_connection.connection_id)

        return Response(status=status.HTTP_201_CREATED, data={"source_id": new_source.source_id})

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
        sync_resource(instance.id)
        return Response(status=status.HTTP_200_OK)
