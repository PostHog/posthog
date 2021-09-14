from typing import Union, cast

from django.db.models import Model
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.serializers import raise_errors_on_nested_writes

from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership, organization
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


class ExplicitTeamMemberSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(source="parent_membership.user", read_only=True)
    parent_level = serializers.IntegerField(source="parent_membership.level", read_only=True)

    class Meta:
        model = ExplicitTeamMembership
        fields = ["id", "parent_membership", "level", "joined_at", "updated_at", "parent_level", "user"]
        read_only_fields = ["user_id", "joined_at", "updated_at"]

    def update(self, updated_membership, validated_data, **kwargs):
        updated_membership = cast(ExplicitTeamMembership, updated_membership)
        raise_errors_on_nested_writes("update", self, validated_data)
        requesting_membership: Union[ExplicitTeamMembership, OrganizationMembership]
        try:
            requesting_membership = ExplicitTeamMembership.objects.select_related("parent_membership").get(
                team_id=updated_membership.team_id, user=self.context["request"].user
            )
        except ExplicitTeamMembership.DoesNotExist:
            requesting_membership = OrganizationMembership.objects.get(
                organization_id=updated_membership.parent_membership.organization_id
            )
        for attr, value in validated_data.items():
            if attr == "level":
                requesting_membership.validate_update(updated_membership, value)
            setattr(updated_membership, attr, value)
        updated_membership.save()
        return updated_membership


class ExplicitTeamMemberViewSet(
    StructuredViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ExplicitTeamMemberSerializer
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions, OrganizationMemberObjectPermissions]
    queryset = ExplicitTeamMembership.objects.select_related("parent_membership", "parent_membership__user")
    lookup_field = "parent_membership__user_id"
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
