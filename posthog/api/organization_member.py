from typing import cast

from django.db.models import Model
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.serializers import raise_errors_on_nested_writes

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
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
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    membership_id = serializers.CharField(source="id", read_only=True)
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = [
            "id",
            "user",
            "membership_id",  # TODO: DEPRECATED in favor of `id` (for consistency)
            "user_id",  # TODO: DEPRECATED in favor of `user`
            "user_first_name",  # TODO: DEPRECATED in favor of `user`
            "user_email",  # TODO: DEPRECATED in favor of `user`
            "level",
            "joined_at",
            "updated_at",
        ]
        read_only_fields = ["user_id", "joined_at", "updated_at"]

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
    queryset = OrganizationMembership.objects.exclude(user__email__endswith="@posthogbot.user")
    lookup_field = "user_id"
    ordering = ["level", "-joined_at"]

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
