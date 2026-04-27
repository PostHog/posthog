from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User


class IsConversationsAdmin(BasePermission):
    message = "Only organization admins can manage conversation channels."

    def has_permission(self, request: Request, view) -> bool:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return False
        try:
            membership = OrganizationMembership.objects.get(
                user=user,
                organization_id=user.current_team.organization_id,
            )
        except OrganizationMembership.DoesNotExist:
            return False
        return membership.level >= OrganizationMembership.Level.ADMIN
