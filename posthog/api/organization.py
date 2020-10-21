from typing import Any, Dict

from django.conf import settings
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, request, response, serializers, status, viewsets

from posthog.models import Organization
from posthog.permissions import CREATE_METHODS, OrganizationAdminWritePermissions, OrganizationMemberPermissions


class PremiumMultiorganizationPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple organizations."

    def has_permission(self, request: request.Request, view) -> bool:
        if (
            not getattr(settings, "MULTI_TENANCY", False)
            and request.method in CREATE_METHODS
            and not request.user.organization.is_feature_available("organizations_projects")
            and request.user.organizations.count() >= 1
        ):
            return False
        return True


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Organization:
        serializers.raise_errors_on_nested_writes("create", self, validated_data)
        request = self.context["request"]
        organization, _, _ = Organization.objects.bootstrap(request.user, **validated_data)
        return organization


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

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            return self.request.user.organization
        filter_kwargs = {self.lookup_field: lookup_value}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def get_queryset(self) -> QuerySet:
        return self.request.user.organizations.all()
