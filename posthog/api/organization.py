from typing import Any, Dict

from django.db import transaction
from django.db.models import QuerySet, query
from django.shortcuts import get_object_or_404
from rest_framework import (
    exceptions,
    mixins,
    permissions,
    request,
    response,
    serializers,
    status,
    viewsets,
)
from rest_framework.generics import DestroyAPIView
from rest_framework.mixins import DestroyModelMixin

from posthog.models import Organization, OrganizationMembership, Team, team
from posthog.permissions import CREATE_METHODS, OrganizationAdminWritePermissions, OrganizationMemberPermissions


class PremiumMultiorganizationPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = (
        "You must upgrade your PostHog plan to be able to create and administrate multiple projects in an organization."
    )

    def has_permission(self, request: request.Request, view) -> bool:
        if (
            request.method in CREATE_METHODS
            and not request.user.is_feature_available("multistructure")
            and request.user.organization.teams.count() >= 1
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
    pagination_class = None
    permission_classes = [
        OrganizationMemberPermissions,
        OrganizationAdminWritePermissions,
        PremiumMultiorganizationPermissions,
    ]
    queryset = Organization.objects.none()
    lookup_field = "id"
    ordering_fields = ["created_by"]
    ordering = ["-created_by"]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        for member in instance.members:
            if member.organizations.count() <= 1:
                raise exceptions.ValidationError(
                    f"Cannot remove organization since that would leave member {member.email} organization-less!"
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
        return Organization.objects.filter(
            id__in=OrganizationMembership.objects.filter(user=self.request.user).values("organization_id")
        )
