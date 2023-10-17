from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import AirbyteResource, DataWarehouseCredential
from posthog.warehouse.airbyte.source import StripeSourcePayload, create_stripe_source
from posthog.warehouse.airbyte.connection import create_connection, retrieve_sync
from posthog.warehouse.api.table import TableSerializer
from posthog.api.routing import StructuredViewSetMixin

from posthog.models import User
from typing import Any
from django.conf import settings


class AirbyteResourceSerializers(serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)

    class Meta:
        model = AirbyteResource
        fields = ["id", "source_id", "created_at", "created_by", "status", "client_secret", "account_id", "source_type"]
        read_only_fields = ["id", "source_id", "created_by", "created_at", "status", "source_type"]


class AirbyteSourceViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Airbyte Sources.
    """

    queryset = AirbyteResource.objects.all()
    serializer_class = AirbyteResourceSerializers
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

    def list(self, request, *args, **kwargs):
        # queryset = self.get_queryset()
        # TODO: temporary as this will spam
        # for airbyte_resource in queryset:
        #     job = retrieve_sync(airbyte_resource.connection_id)
        #     airbyte_resource.status = job["status"]
        #     airbyte_resource.save()

        return super().list(request, *args, **kwargs)

    def retrieve(self, *args, **kwargs):
        super_cls = super()

        airbyte_resource = self.get_object()
        job = retrieve_sync(airbyte_resource.connection_id)
        airbyte_resource.status = job["status"]
        airbyte_resource.save()

        return super_cls.retrieve(*args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        account_id = request.data["account_id"]
        client_secret = request.data["client_secret"]

        stripe_payload = StripeSourcePayload(
            account_id=account_id,
            client_secret=client_secret,
        )
        new_source = create_stripe_source(stripe_payload)
        new_connection = create_connection(new_source.source_id)

        AirbyteResource.objects.create(
            source_id=new_source.source_id,
            connection_id=new_connection.connection_id,
            team=self.request.user.current_team,
            loading=True,
        )

        credential = DataWarehouseCredential.objects.create(
            team_id=self.team_id,
            access_key=settings.AIRBYTE_BUCKET_KEY,
            access_secret=settings.AIRBYTE_BUCKET_SECRET,
        )

        # TODO: make sure env vars are properly managed
        new_table = TableSerializer(
            data={
                "credential": {
                    "access_key": credential.access_key,
                    "access_secret": credential.access_secret,
                },
                "name": "stripe_customers",
                "format": "Parquet",
                "url_pattern": "https://databeach-hackathon.s3.amazonaws.com/airbyte-test/customers/*.parquet",
            },
            context=self.get_serializer_context(),
        )
        new_table.is_valid(raise_exception=True)
        new_table.save()

        return Response(status=status.HTTP_201_CREATED, data={"source_id": new_source.source_id})
