from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User


class IsConversationsAdmin(BasePermission):
    message = "Only organization admins can manage conversation channels."

    def has_permission(self, request: Request, view) -> bool:
        user = request.user
        if not isinstance(user, User):
            return False

        # On project-nested viewsets (TeamAndOrgViewSetMixin) gate on the *routed* team's
        # organization so an org admin can't target another project by ID. Plain APIViews
        # have no routed team, so fall back to the user's current team.
        organization_id = None
        try:
            routed_team = view.team
        except Exception:
            routed_team = None
        if routed_team is not None:
            organization_id = routed_team.organization_id
        elif user.current_team is not None:
            organization_id = user.current_team.organization_id

        if organization_id is None:
            return False
        try:
            membership = OrganizationMembership.objects.get(
                user=user,
                organization_id=organization_id,
            )
        except OrganizationMembership.DoesNotExist:
            return False
        return membership.level >= OrganizationMembership.Level.ADMIN
