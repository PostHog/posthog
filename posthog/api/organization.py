from typing import Any, Dict, Optional

from django.conf import settings
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, request, response, serializers, status, viewsets

from posthog.models import Organization
from posthog.models.organization import OrganizationMembership
from posthog.permissions import CREATE_METHODS, OrganizationAdminWritePermissions, OrganizationMemberPermissions


class PremiumMultiorganizationPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple organizations."

    def has_permission(self, request: request.Request, view) -> bool:
        if (
            # make multiple orgs only premium on self-hosted, since enforcement of this is not possible on Cloud
            not getattr(settings, "MULTI_TENANCY", False)
            and request.method in CREATE_METHODS
            and (
                request.user.organization is None
                or not request.user.organization.is_feature_available("organizations_projects")
            )
            and request.user.organizations.count() >= 1
        ):
            return False
        return True


class OrganizationSerializer(serializers.ModelSerializer):
    membership_level = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "created_at", "updated_at", "membership_level"]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Organization:
        serializers.raise_errors_on_nested_writes("create", self, validated_data)
        organization, _, _ = Organization.objects.bootstrap(self.context["request"].user, **validated_data)
        return organization

    def get_membership_level(self, organization: Organization) -> Optional[OrganizationMembership.Level]:
        membership = OrganizationMembership.objects.filter(
            organization=organization, user=self.context["request"].user
        ).first()
        return membership.level if membership is not None else None


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        PremiumMultiorganizationPermissions,
        OrganizationMemberPermissions,
        OrganizationAdminWritePermissions,
    ]
    queryset = Organization.objects.none()
    lookup_field = "id"
    ordering = "-created_by"

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        for member in instance.members.all():
            if member.organizations.count() <= 1:
                raise exceptions.ValidationError(
                    f"Cannot remove organization since that would leave member {member.email} organization-less, which is not supported yet."
                )
        self.perform_destroy(instance)
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self) -> QuerySet:
        return self.request.user.organizations.all()

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            organization = self.request.user.organization
            if organization is None:
                raise exceptions.NotFound("Current organization not found.")
            return organization
        filter_kwargs = {self.lookup_field: lookup_value}
        organization = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, organization)
        return organization
