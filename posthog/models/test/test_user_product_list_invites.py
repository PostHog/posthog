from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.file_system.user_product_list import DEFAULT_PRODUCT_PATHS, UserProductList
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite

from ee.models.rbac.access_control import AccessControl


class TestUserProductListDefaults(BaseTest):
    def _default_paths_for(self, user: User, team: Team) -> set[str]:
        return set(
            UserProductList.objects.filter(
                user=user, team=team, enabled=True, reason=UserProductList.Reason.DEFAULT
            ).values_list("product_path", flat=True)
        )

    def _make_team_private(self, team: Team) -> None:
        # Project-level access controls only apply when the org has the feature.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        AccessControl.objects.create(team=team, resource="project", resource_id=str(team.id), access_level="none")

    def test_accepting_invite_adds_default_products_for_private_project_access(self):
        # Mark the team private, so seeding can only come from the invite's access grant,
        # not from the org-wide seeding in User.join.
        self._make_team_private(self.team)
        new_user = User.objects.create_user(email="newuser@posthog.com", password="password", first_name="New")

        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="newuser@posthog.com",
            private_project_access=[{"id": self.team.id, "level": "member"}],
        )
        invite.use(new_user, prevalidated=True)

        assert self._default_paths_for(new_user, self.team) == set(DEFAULT_PRODUCT_PATHS)

    def test_accepting_invite_without_private_project_access_adds_default_products(self):
        new_user = User.objects.create_user(email="newuser@posthog.com", password="password", first_name="New")

        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="newuser@posthog.com",
            private_project_access=None,
        )
        invite.use(new_user, prevalidated=True)

        assert self._default_paths_for(new_user, self.team) == set(DEFAULT_PRODUCT_PATHS)

    def test_creating_team_adds_default_products_for_all_users_with_access(self):
        member = User.objects.create_user(email="member@posthog.com", password="password", first_name="Member")
        member.join(organization=self.organization)
        creator = User.objects.create_user(email="creator@posthog.com", password="password", first_name="Creator")
        creator.join(organization=self.organization)

        new_team = Team.objects.create_with_data(
            initiating_user=creator, organization=self.organization, name="New Team"
        )

        assert self._default_paths_for(creator, new_team) == set(DEFAULT_PRODUCT_PATHS)
        assert self._default_paths_for(member, new_team) == set(DEFAULT_PRODUCT_PATHS)

    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_access_control_signal_adds_default_products(self):
        # Private team: joining the org must NOT seed it; the explicit access grant must.
        self._make_team_private(self.team)
        user = User.objects.create_user(email="signal@posthog.com", password="password", first_name="Signal")
        user.join(organization=self.organization)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=user)

        assert self._default_paths_for(user, self.team) == set()

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=membership,
            access_level="member",
        )

        assert self._default_paths_for(user, self.team) == set(DEFAULT_PRODUCT_PATHS)
