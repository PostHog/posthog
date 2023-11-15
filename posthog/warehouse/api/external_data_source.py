from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import ExternalDataSource
from posthog.warehouse.external_data_source.workspace import get_or_create_workspace
from posthog.warehouse.external_data_source.source import create_source, delete_source
from posthog.warehouse.external_data_source.source_definitions import SOURCE_TYPE_MAPPING
from posthog.warehouse.external_data_source.connection import (
    create_connection,
    start_sync,
    get_connection_streams_by_external_data_source,
    get_active_connection_streams_by_id,
    update_connection_stream,
)
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
    stream_count = serializers.SerializerMethodField()

    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "source_id",
            "destination_id",
            "created_at",
            "created_by",
            "status",
            "client_secret",
            "account_id",
            "source_type",
            "stream_count",
        ]
        read_only_fields = [
            "id",
            "source_id",
            "destination_id",
            "created_by",
            "created_at",
            "status",
            "source_type",
            "stream_count",
        ]

    def get_stream_count(self, obj):
        return len(get_active_connection_streams_by_id(obj.connection_id))


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
        payload = request.data["payload"]
        payload_type = request.data["payload_type"]

        if payload_type not in SOURCE_TYPE_MAPPING.keys():
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": f"Payload type {payload_type} is not supported."},
            )

        workspace_id = get_or_create_workspace(self.team_id)
        new_source = create_source(payload_type, payload, workspace_id)

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
            source_type=payload_type,
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

    @action(methods=["GET"], detail=True)
    def streams(self, *args: Any, **kwargs: Any):
        instance = self.get_object()
        available_streams_for_connection = get_connection_streams_by_external_data_source(instance)
        current_connection_streams = get_active_connection_streams_by_id(instance.connection_id)
        return Response(
            status=status.HTTP_200_OK,
            data={
                "available_streams_for_connection": [
                    {"streamName": stream["streamName"]} for stream in available_streams_for_connection
                ],
                "current_connection_streams": [{"streamName": stream["name"]} for stream in current_connection_streams],
            },
        )

    @action(methods=["PATCH"], detail=True)
    def active_streams(self, request: Request, *args: Any, **kwargs: Any):
        instance = self.get_object()
        update_connection_stream(instance.connection_id, request.data["streams"])
        return Response(status=status.HTTP_200_OK)
