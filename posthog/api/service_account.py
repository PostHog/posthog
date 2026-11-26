from typing import Any, cast
from uuid import UUID

from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership, User
from posthog.permissions import OrganizationAdminReadPermissions, TimeSensitiveActionPermission
from posthog.service_accounts import operations
from posthog.utils import posthoganalytics


class ServiceAccountSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(
        source="user.uuid", read_only=True, help_text="Stable identifier of the service account."
    )
    name = serializers.CharField(
        source="user.first_name", read_only=True, help_text="Display name of the service account."
    )
    user = UserBasicSerializer(read_only=True, help_text="User identity used for permissions and object attribution.")
    is_active = serializers.BooleanField(
        source="user.is_active", read_only=True, help_text="Whether credentials can authenticate as this account."
    )
    created_at = serializers.DateTimeField(
        source="user.date_joined", read_only=True, help_text="When the service account was created."
    )

    class Meta:
        model = OrganizationMembership
        fields = ["id", "name", "user", "is_active", "created_at"]


class ServiceAccountActionSerializer(serializers.Serializer):
    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unknown_fields = set(self.initial_data) - self.fields.keys()
        if unknown_fields:
            raise serializers.ValidationError(dict.fromkeys(unknown_fields, "This field cannot be set."))
        return attrs


class ServiceAccountWriteSerializer(ServiceAccountActionSerializer):
    name = serializers.CharField(max_length=150, help_text="Display name of the service account.")


@extend_schema(extensions={"x-product": "core"})
class ServiceAccountViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "organization_member"
    queryset = OrganizationMembership.objects.none()
    serializer_class = ServiceAccountSerializer
    permission_classes = [OrganizationAdminReadPermissions, TimeSensitiveActionPermission]
    lookup_field = "user__uuid"
    lookup_url_kwarg = "pk"
    path_parameters = {"pk": UUID}
    http_method_names = ["get", "post", "patch", "head", "options"]
    time_sensitive_allow_actions = ["partial_update"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return operations.service_accounts(self.organization)

    @validated_request(ServiceAccountWriteSerializer, responses={201: ServiceAccountSerializer})
    def create(self, request: ValidatedRequest, **kwargs) -> Response:
        if not posthoganalytics.feature_enabled(
            "service-accounts",
            str(cast(User, request.user).distinct_id),
            groups={"organization": str(self.organization.id)},
            group_properties={"organization": {"id": str(self.organization.id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        ):
            raise PermissionDenied("Service account creation is not enabled for this organization.")
        membership = operations.create_service_account(self.organization, name=request.validated_data["name"])
        return Response(self.get_serializer(membership).data, status=status.HTTP_201_CREATED)

    @validated_request(ServiceAccountWriteSerializer, responses={200: ServiceAccountSerializer})
    def partial_update(self, request: ValidatedRequest, **kwargs) -> Response:
        membership = self.get_object()
        membership = operations.rename_service_account(
            self.organization, membership.user.uuid, name=request.validated_data["name"]
        )
        return Response(self.get_serializer(membership).data)

    @action(methods=["POST"], detail=True, required_scopes=["organization_member:write"])
    @validated_request(ServiceAccountActionSerializer, responses={200: ServiceAccountSerializer})
    def disable(self, request: ValidatedRequest, **kwargs) -> Response:
        membership = self.get_object()
        membership = operations.set_service_account_active(self.organization, membership.user.uuid, is_active=False)
        return Response(self.get_serializer(membership).data)

    @action(methods=["POST"], detail=True, required_scopes=["organization_member:write"])
    @validated_request(ServiceAccountActionSerializer, responses={200: ServiceAccountSerializer})
    def enable(self, request: ValidatedRequest, **kwargs) -> Response:
        membership = self.get_object()
        membership = operations.set_service_account_active(self.organization, membership.user.uuid, is_active=True)
        return Response(self.get_serializer(membership).data)
