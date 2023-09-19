from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.permissions import OrganizationMemberPermissions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework import filters, serializers, viewsets
from posthog.warehouse.models import AirbyteSource
from posthog.warehouse.airbyte import StripeSourcePayload, create_stripe_source
from posthog.api.routing import StructuredViewSetMixin

from posthog.models import User
from typing import Any


class AirbyteSourceSerializers(serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)

    class Meta:
        model = AirbyteSource
        fields = ["id", "source_id", "created_at", "created_by"]
        read_only_fields = [
            "id",
            "source_id",
            "created_by",
            "created_at",
        ]


class AirbyteSourceViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Airbyte Sources.
    """

    queryset = AirbyteSource.objects.all()
    serializer_class = AirbyteSourceSerializers
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ["source_id"]
    ordering = "-created_at"

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        if self.action == "list":
            return (
                self.queryset.filter(team_id=self.team_id)
                .exclude(deleted=True)
                .prefetch_related("created_by")
                .order_by(self.ordering)
            )

        return self.queryset.filter(team_id=self.team_id).prefetch_related("created_by").order_by(self.ordering)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        account_id = request.data["account_id"]
        client_secret = request.data["client_secret"]

        stripe_payload = StripeSourcePayload(
            account_id=account_id,
            client_secret=client_secret,
        )
        stripe_response = create_stripe_source(stripe_payload)

        AirbyteSource.objects.create(source_id=stripe_response.source_id, team=self.request.user.current_team)

        return Response(status=status.HTTP_201_CREATED, data={"source_id": stripe_response.source_id})
