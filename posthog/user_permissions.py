from functools import cached_property
from typing import Optional
from posthog.models import User, Team, Organization, OrganizationMembership

class UserPermissions:
    def __init__(self, user: User, team: Team, organization: Organization):
        self.user = user
        self.team = team
        self.organization = organization

    @cached_property
    def team_effective_membership_level(self) -> Optional[OrganizationMembership.Level]:
        return self.team.get_effective_membership_level(self.user.pk)


