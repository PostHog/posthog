from django.db.models import QuerySet, query
from rest_framework import exceptions, mixins, response, serializers, status, viewsets

from posthog.models import OrganizationMembership
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions


class OrganizationMembershipSerializer(serializers.ModelSerializer):
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    membership_id = serializers.CharField(source="id", read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = ["membership_id", "user_id", "user_first_name", "user_email", "level", "joined_at", "updated_at"]


class OrganizationMemberViewSet(
    mixins.DestroyModelMixin, mixins.UpdateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    serializer_class = OrganizationMembershipSerializer
    pagination_class = None
    permission_classes = [OrganizationMemberPermissions, OrganizationAdminWritePermissions]
    queryset = OrganizationMembership.objects.none()
    lookup_field = "user_id"

    def get_queryset(self) -> QuerySet:
        return (
            OrganizationMembership.objects.filter(organization=self.request.user.organization)
            .select_related("user")
            .order_by("-joined_at")
        )

    def destroy(self, request, *args, **kwargs):
        """Member removal with validation (admin permissions)."""
        member_to_delete = self.get_object()
        try:
            if (
                request.user.organization_memberships.get(organization=request.user.organization).level
                < OrganizationMembership.Level.ADMIN
            ):
                raise exceptions.PermissionDenied("You are not permitted to delete organization members.")
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound("User does not exist or does not belong to the organization.")
        if member_to_delete == request.user:
            raise exceptions.ValidationError("Cannot delete yourself.")
        OrganizationMembership.objects.get(organization=request.user.organization, user=member_to_delete)
        return response.Response(status=status.HTTP_204_NO_CONTENT)
