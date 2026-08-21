from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models import TeamAccessControlConfig
from products.dashboards.backend.models.dashboard import Dashboard

from ee.api.test.base import APILicensedTest
from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role

TERRAFORM_UA = "posthog/terraform-provider 1.2.3"


class TestAccessControlManagement(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Managed dashboard")

    def _put_rule(self, access_level, *, as_terraform=False):
        headers = {"user-agent": TERRAFORM_UA} if as_terraform else {}
        return self.client.put(
            f"/api/projects/@current/dashboards/{self.dashboard.id}/access_controls",
            {"access_level": access_level},
            headers=headers,
        )

    def _rule(self):
        return AccessControl.objects.get(team=self.team, resource="dashboard", resource_id=str(self.dashboard.id))

    def _lock(self, enabled=True):
        TeamAccessControlConfig.objects.update_or_create(
            team=self.team, defaults={"lock_terraform_managed_rules": enabled}
        )

    def test_terraform_write_stamps_the_rule(self):
        assert self._put_rule("viewer", as_terraform=True).status_code == status.HTTP_200_OK
        rule = self._rule()
        assert rule.managed_by == "terraform"
        assert rule.managed_at is not None

    def test_web_write_leaves_the_rule_unmanaged(self):
        assert self._put_rule("viewer").status_code == status.HTTP_200_OK
        assert self._rule().managed_by is None

    @parameterized.expand([("edit", "editor"), ("delete", None)])
    def test_locked_rule_refuses_a_web_write(self, _name, access_level):
        self._put_rule("viewer", as_terraform=True)
        self._lock()

        res = self._put_rule(access_level)

        assert res.status_code == status.HTTP_403_FORBIDDEN, res.json()
        assert self._rule().access_level == "viewer"

    @parameterized.expand([("edit", "editor"), ("delete", None)])
    def test_terraform_still_changes_its_own_locked_rule(self, _name, access_level):
        self._put_rule("viewer", as_terraform=True)
        self._lock()

        res = self._put_rule(access_level, as_terraform=True)

        assert res.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT), res.content

    def test_managed_rule_stays_editable_while_the_lock_is_off(self):
        self._put_rule("viewer", as_terraform=True)

        assert self._put_rule("editor").status_code == status.HTTP_200_OK
        assert self._rule().access_level == "editor"

    def test_unmanaged_rule_for_another_subject_stays_editable(self):
        self._put_rule("viewer", as_terraform=True)
        self._lock()
        role = Role.objects.create(name="Support", organization=self.organization)

        res = self.client.put(
            f"/api/projects/@current/dashboards/{self.dashboard.id}/access_controls",
            {"access_level": "editor", "role": str(role.id)},
        )

        assert res.status_code == status.HTTP_200_OK, res.json()

    def test_claim_stamps_a_rule_terraform_never_wrote(self):
        self._put_rule("viewer")

        res = self.client.put(
            "/api/projects/@current/access_control_management",
            {"resource": "dashboard", "resource_id": str(self.dashboard.id), "managed_by": "terraform"},
        )

        assert res.status_code == status.HTTP_200_OK, res.json()
        assert self._rule().managed_by == "terraform"

    def test_release_unlocks_a_stranded_rule(self):
        self._put_rule("viewer", as_terraform=True)
        self._lock()

        res = self.client.put(
            "/api/projects/@current/access_control_management",
            {"resource": "dashboard", "resource_id": str(self.dashboard.id), "managed_by": None},
            headers={"user-agent": TERRAFORM_UA},
        )

        assert res.status_code == status.HTTP_200_OK, res.json()
        assert self._rule().managed_by is None
        assert self._put_rule("editor").status_code == status.HTTP_200_OK

    def test_claim_is_refused_for_a_locked_rule_from_the_web(self):
        self._put_rule("viewer", as_terraform=True)
        self._lock()

        res = self.client.put(
            "/api/projects/@current/access_control_management",
            {"resource": "dashboard", "resource_id": str(self.dashboard.id), "managed_by": None},
        )

        assert res.status_code == status.HTTP_403_FORBIDDEN, res.json()

    def test_settings_endpoint_reports_and_sets_the_lock(self):
        self._put_rule("viewer", as_terraform=True)

        res = self.client.patch(
            "/api/projects/@current/access_control_management_settings",
            {"lock_terraform_managed_rules": True},
        )

        assert res.status_code == status.HTTP_200_OK, res.json()
        assert res.json() == {"lock_terraform_managed_rules": True, "has_terraform_managed_rules": True}
        assert self._put_rule("editor").status_code == status.HTTP_403_FORBIDDEN

    def test_role_delete_is_refused_when_it_would_drop_a_locked_rule(self):
        role = Role.objects.create(name="Engineering", organization=self.organization)
        self.client.put(
            f"/api/projects/@current/dashboards/{self.dashboard.id}/access_controls",
            {"access_level": "editor", "role": str(role.id)},
            headers={"user-agent": TERRAFORM_UA},
        )
        self._lock()

        res = self.client.delete(f"/api/organizations/@current/roles/{role.id}")

        assert res.status_code == status.HTTP_403_FORBIDDEN, res.content
        assert Role.objects.filter(id=role.id).exists()

    def test_role_delete_is_allowed_when_no_locked_rule_uses_it(self):
        role = Role.objects.create(name="Engineering", organization=self.organization)

        res = self.client.delete(f"/api/organizations/@current/roles/{role.id}")

        assert res.status_code == status.HTTP_204_NO_CONTENT, res.content
