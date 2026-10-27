from __future__ import annotations

from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, Team, User
from posthog.user_permissions import UserPermissions, user_can_access_team

from products.access_control.backend.facade.user_access_control import ACCESS_CONTROL_RESOURCES, UserAccessControl

from ..facade.enums import BetsAccessLevel

BETS_RESOURCE = "bets"

_POSTHOG_LEVEL_TO_BETS = {
    "manager": BetsAccessLevel.MANAGER,
    "editor": BetsAccessLevel.TRADER,
    "viewer": BetsAccessLevel.VIEWER,
}


@frozen
class Member:
    user_id: int
    name: str
    email: str


class PostHogIdentity:
    def access_level(self, user: User, team: Team) -> BetsAccessLevel | None:
        membership = OrganizationMembership.objects.filter(organization_id=team.organization_id, user=user).first()
        if membership is None or not user_can_access_team(user, team):
            return None
        if membership.level >= OrganizationMembership.Level.ADMIN:
            return BetsAccessLevel.MANAGER
        access_control = UserAccessControl(user=user, team=team)
        if access_control.access_level_for_object(team, resource="project", specific_only=True) == "admin":
            return BetsAccessLevel.MANAGER
        if BETS_RESOURCE not in ACCESS_CONTROL_RESOURCES:
            return BetsAccessLevel.TRADER
        resolved = access_control.access_level_for_resource(BETS_RESOURCE)
        if resolved is None:
            return BetsAccessLevel.TRADER
        return _POSTHOG_LEVEL_TO_BETS.get(resolved.access_level)

    def has_project_access(self, user_id: int, team: Team) -> bool:
        user = User.objects.filter(id=user_id, is_active=True).first()
        if user is None:
            return False
        return UserPermissions(user).team(team).effective_membership_level is not None

    def members(self, user_ids: set[int]) -> dict[int, Member]:
        users = User.objects.filter(id__in=user_ids).only("id", "first_name", "last_name", "email")
        return {
            user.id: Member(user_id=user.id, name=user.first_name or user.email.split("@")[0], email=user.email)
            for user in users
        }

    def managers(self, team: Team) -> list[int]:
        return list(
            OrganizationMembership.objects.filter(
                organization_id=team.organization_id, level__gte=OrganizationMembership.Level.ADMIN
            ).values_list("user_id", flat=True)
        )

    def project_member_ids(self, team: Team) -> list[int]:
        return list(
            OrganizationMembership.objects.filter(organization_id=team.organization_id).values_list(
                "user_id", flat=True
            )
        )
