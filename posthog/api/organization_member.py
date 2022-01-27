from typing import cast

from django.db.models import Model
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import raise_errors_on_nested_writes

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import OrganizationMemberPermissions, extract_organization


class OrganizationMemberObjectPermissions(BasePermission):
    """Require organization admin level to change object, allowing everyone read AND delete."""

    message = "Your cannot edit other organization members."

    def has_object_permission(self, request: Request, view, membership: OrganizationMembership) -> bool:
        if request.method in SAFE_METHODS:
            return True
        organization = extract_organization(membership)
        requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user_id=cast(User, request.user).id, organization=organization
        )
        try:
            requesting_membership.validate_update(membership)
        except exceptions.ValidationError:
            return False
        return True


class OrganizationMemberSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = [
            "id",
            "user",
            "level",
            "joined_at",
            "updated_at",
        ]
        read_only_fields = ["id", "joined_at", "updated_at"]

    def update(self, updated_membership, validated_data, **kwargs):
        updated_membership = cast(OrganizationMembership, updated_membership)
        raise_errors_on_nested_writes("update", self, validated_data)
        requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
            organization=updated_membership.organization, user=self.context["request"].user
        )
        for attr, value in validated_data.items():
            if attr == "level":
                requesting_membership.validate_update(updated_membership, value)
            setattr(updated_membership, attr, value)
        updated_membership.save()
        return updated_membership


class OrganizationMemberViewSet(
    StructuredViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrganizationMemberSerializer
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions, OrganizationMemberObjectPermissions]
    queryset = OrganizationMembership.objects.all().order_by(Lower('user__first_name')).exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
    lookup_field = "user__uuid"
    ordering = ["level", "-joined_at"]

    def list(self, request, *args, **kwargs):
        #put the loggedInUser object on top as per issue:8234
        queryset = self.filter_queryset(self.get_queryset())
        loggedInUser  = queryset.filter(user = request.user).first()
        queryset = queryset.exclude(user = request.user)
        queryset = [loggedInUser] + list(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return queryset.get(user=self.request.user)
        filter_kwargs = {self.lookup_field: lookup_value}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def perform_destroy(self, instance: Model):
        instance = cast(OrganizationMembership, instance)
        instance.user.leave(organization=instance.organization)
