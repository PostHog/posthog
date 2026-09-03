import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.organization import Organization, OrganizationMembership

from products.access_control.backend.facade import contracts
from products.access_control.backend.facade.api import InvalidObjectAccessControlError, set_object_access_control
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.dashboards.backend.models.dashboard import Dashboard


class TestSetObjectAccessControl(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")
        self.other_membership = OrganizationMembership.objects.get(user=self.other_user, organization=self.organization)
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id=None, access_level="none")

    def _grant(self, access_level: str | None, **overrides: object) -> contracts.ObjectAccessControlRule | None:
        input_kwargs: dict = {
            "resource": "dashboard",
            "resource_id": str(self.dashboard.id),
            "access_level": access_level,
            "organization_member_id": self.other_membership.id,
        }
        input_kwargs.update(overrides)
        return set_object_access_control(
            team_id=self.team.id, input=contracts.SetObjectAccessControlInput(**input_kwargs)
        )

    def _other_user_level(self) -> str | None:
        return UserAccessControl(user=self.other_user, team=self.team).get_user_access_level(self.dashboard)

    def test_grant_update_and_revoke_are_visible_through_user_access_control(self) -> None:
        assert self._other_user_level() == "none"

        rule = self._grant("viewer")
        assert rule is not None and rule.access_level == "viewer"
        assert self._other_user_level() == "viewer"

        updated = self._grant("editor")
        assert updated is not None and updated.id == rule.id
        assert self._other_user_level() == "editor"

        assert self._grant(None) is None
        assert self._other_user_level() == "none"
        assert self._grant(None) is None

    def test_role_rule_grants_role_members(self) -> None:
        role = Role.objects.create(name="Sales", organization=self.organization)
        RoleMembership.objects.create(user=self.other_user, role=role)

        self._grant("viewer", organization_member_id=None, role_id=role.id)

        assert self._other_user_level() == "viewer"

    @parameterized.expand(
        [
            ("unknown_resource", {"resource": "not_a_resource"}),
            ("internal_resource", {"resource": "INTERNAL"}),
            ("unknown_level", {"access_level": "owner"}),
            ("level_below_resource_minimum", {"resource": "action", "access_level": "none"}),
            ("level_above_resource_maximum", {"resource": "activity_log", "access_level": "editor"}),
        ]
    )
    def test_rejects_invalid_rules(self, _name: str, overrides: dict) -> None:
        with pytest.raises(InvalidObjectAccessControlError):
            self._grant("viewer", **overrides)
        assert not AccessControl.objects.filter(resource_id=str(self.dashboard.id)).exists()

    def test_rejects_subjects_from_another_organization(self) -> None:
        other_org = Organization.objects.create(name="Other")
        outsider = User.objects.create_and_join(other_org, "outsider@posthog.com", "testtest")
        outsider_membership = OrganizationMembership.objects.get(user=outsider, organization=other_org)
        other_org_role = Role.objects.create(name="Outside", organization=other_org)

        with pytest.raises(InvalidObjectAccessControlError):
            self._grant("viewer", organization_member_id=outsider_membership.id)
        with pytest.raises(InvalidObjectAccessControlError):
            self._grant("viewer", organization_member_id=None, role_id=other_org_role.id)

    def test_requires_exactly_one_subject(self) -> None:
        role = Role.objects.create(name="Sales", organization=self.organization)
        with pytest.raises(ValueError):
            self._grant("viewer", organization_member_id=None)
        with pytest.raises(ValueError):
            self._grant("viewer", role_id=role.id)
