import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.serializers import ValidationError

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team

from products.access_control.backend.facade.api import AccessControl
from products.cross_project_dashboards.backend.logic import assert_can_reference_insight
from products.product_analytics.backend.facade.models import Insight


class TestAssertCanReferenceInsight(BaseTest):
    def test_allows_an_insight_in_a_reachable_project(self):
        insight = Insight.objects.create(team=self.team, name="Signups")
        assert_can_reference_insight(self.user, self.organization.id, self.team.pk, insight.pk)

    def test_rejects_an_insight_in_another_organization_the_user_belongs_to(self):
        other_organization = Organization.objects.create(name="Other")
        OrganizationMembership.objects.create(organization=other_organization, user=self.user)
        other_team = Team.objects.create(organization=other_organization, name="Other project")
        insight = Insight.objects.create(team=other_team, name="Secret")
        with pytest.raises(ValidationError):
            assert_can_reference_insight(self.user, self.organization.id, other_team.pk, insight.pk)

    def test_rejects_an_insight_that_does_not_exist(self):
        with pytest.raises(ValidationError):
            assert_can_reference_insight(self.user, self.organization.id, self.team.pk, 999999)

    def test_rejects_a_project_that_does_not_exist(self):
        with pytest.raises(ValidationError):
            assert_can_reference_insight(self.user, self.organization.id, 999999, 1)

    def test_rejects_an_insight_from_a_different_project(self):
        other_team = Team.objects.create(organization=self.organization, name="Second project")
        insight = Insight.objects.create(team=other_team, name="Elsewhere")
        with pytest.raises(ValidationError):
            assert_can_reference_insight(self.user, self.organization.id, self.team.pk, insight.pk)

    @parameterized.expand(
        [
            # Resource and object rules fall back to a permissive default, so without the separate
            # has_project_access check this user reaches an insight in a project they were denied.
            ("everyone_denied", True, "none"),
            # Legacy resolution takes the highest matching project rule, so an allow for everyone
            # outranks this member's explicit denial unless membership is checked as well.
            ("member_denied_under_legacy_resolution", False, "member"),
        ]
    )
    def test_honors_a_project_level_deny_in_the_insight_own_project(
        self, _name: str, most_specific_resolution: bool, everyone_level: str
    ):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.uses_most_specific_access_resolution = most_specific_resolution
        self.organization.save()
        denied_team = Team.objects.create(organization=self.organization, name="Denied project")
        insight = Insight.objects.create(team=denied_team, name="Out of reach")
        AccessControl.objects.create(
            team=denied_team, resource="project", resource_id=str(denied_team.id), access_level=everyone_level
        )
        if everyone_level != "none":
            AccessControl.objects.create(
                team=denied_team,
                resource="project",
                resource_id=str(denied_team.id),
                organization_member=OrganizationMembership.objects.get(organization=self.organization, user=self.user),
                access_level="none",
            )

        with pytest.raises(ValidationError):
            assert_can_reference_insight(self.user, self.organization.id, denied_team.pk, insight.pk)
