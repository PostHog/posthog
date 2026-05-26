from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.team_scoping import get_scoped_team_ids

from posthog.constants import AvailableFeature
from posthog.models import Project
from posthog.models.organization import OrganizationMembership

from ee.models.rbac.access_control import AccessControl


class TestTeamScoping(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {
                "name": AvailableFeature.ACCESS_CONTROL,
                "key": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.can_query_across_organization_projects = True
        self.team.save()

    def test_cross_project_team_ids_are_limited_to_user_visible_teams(self) -> None:
        _, visible_team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)
        _, hidden_team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)

        AccessControl.objects.create(
            team=hidden_team,
            resource="project",
            resource_id=str(hidden_team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        scoped_team_ids = get_scoped_team_ids(self.team, user=self.user)

        assert self.team.id in scoped_team_ids
        assert visible_team.id in scoped_team_ids
        assert hidden_team.id not in scoped_team_ids

    def test_cross_project_team_ids_do_not_expand_without_user(self) -> None:
        _, other_team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)

        scoped_team_ids = get_scoped_team_ids(self.team)

        assert self.team.id in scoped_team_ids
        assert other_team.id not in scoped_team_ids

    def test_hogql_context_passes_user_to_team_scoping(self) -> None:
        _, hidden_team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)

        AccessControl.objects.create(
            team=hidden_team,
            resource="project",
            resource_id=str(hidden_team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        scoped_team_ids = HogQLContext(team=self.team, user=self.user).query_team_ids

        assert self.team.id in scoped_team_ids
        assert hidden_team.id not in scoped_team_ids
