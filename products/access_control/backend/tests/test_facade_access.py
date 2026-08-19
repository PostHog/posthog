import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.facade.access import ProjectAccess, required_level_for
from products.dashboards.backend.models.dashboard import Dashboard

from ee.models.rbac.access_control import AccessControl


class TestProjectAccess(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.member = User.objects.create_and_join(self.organization, "member@posthog.com", "testtest")
        self.membership = OrganizationMembership.objects.get(user=self.member, organization=self.organization)
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self.member_access = ProjectAccess.for_user(self.member, self.team)

    @parameterized.expand(
        [
            ("view", "dashboard", "viewer"),
            ("edit", "dashboard", "editor"),
            ("manage", "dashboard", "manager"),
            ("view", "project", "member"),
            ("edit", "project", "admin"),
            ("manage", "project", "admin"),
        ]
    )
    def test_required_level_is_a_rung_on_the_resource_ladder(self, action, resource, expected) -> None:
        assert required_level_for(resource, action) == expected

    def test_object_rule_decides_object_checks_but_not_resource_checks(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(self.dashboard.id),
            organization_member=self.membership,
            access_level="none",
        )

        assert self.member_access.check("view", self.dashboard) is False
        assert self.member_access.check("edit", "dashboard") is True

        decision = self.member_access.decide("view", self.dashboard)
        assert (
            decision.allowed,
            decision.level,
            decision.required_level,
            decision.source,
            decision.source_subject,
        ) == (
            False,
            "none",
            "viewer",
            "object",
            "member",
        )
        with pytest.raises(PermissionDenied):
            self.member_access.require("view", self.dashboard)

    def test_creator_bypasses_object_rules_and_filter_hides_denied_objects(self) -> None:
        AccessControl.objects.create(
            team=self.team, resource="dashboard", resource_id=str(self.dashboard.id), access_level="none"
        )
        creator_access = ProjectAccess.for_user(self.user, self.team)

        assert creator_access.decide("edit", self.dashboard).source == "creator"
        assert list(creator_access.filter(Dashboard.objects.filter(team=self.team))) == [self.dashboard]
        assert list(self.member_access.filter(Dashboard.objects.filter(team=self.team))) == []

    def test_unauthenticated_request_gets_a_closed_handle(self) -> None:
        class AnonymousRequest:
            class user:
                is_authenticated = False
                is_anonymous = True

        access = ProjectAccess.for_request(AnonymousRequest(), self.team)  # type: ignore[arg-type]

        assert access.check("view", self.dashboard) is False
        assert list(access.filter(Dashboard.objects.filter(team=self.team))) == []
