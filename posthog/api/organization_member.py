from django.db.models import QuerySet
from rest_framework import exceptions, mixins, response, status, viewsets

from posthog.api.user import UserSerializer
from posthog.models import MembershipLevel, Organization, OrganizationMembership, User


class OrganizationMemberViewSet(
    mixins.DestroyModelMixin, mixins.UpdateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    serializer_class = UserSerializer
    lookup_field = "distinct_id"

    def get_queryset(self) -> QuerySet:
        return self.request.user.organization.members.all()

    def destroy(self, request, *args, **kwargs):
        """Member removal with validation (admin permissions)."""
        member_to_delete = self.get_object()
        try:
            if (
                OrganizationMembership.objects.get(user=request.user, organization=request.user.organization).level
                < MembershipLevel.ADMIN
            ):
                raise exceptions.PermissionDenied({"detail": "You are not permitted to delete organization members."})
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound({"detail": "User does not belong to the organization."})
        if member_to_delete == request.user:
            raise exceptions.ValidationError({"detail": "Cannot delete yourself."})
        request.user.organization.members.remove(member_to_delete)
        return response.Response(status=status.HTTP_204_NO_CONTENT)
