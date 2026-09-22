from posthog.test.base import BaseTest

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard import Dashboard


class TestObjectRuleCleanup(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Doomed", created_by=self.user)
        self.other = Dashboard.objects.create(team=self.team, name="Kept", created_by=self.user)
        for dashboard in (self.dashboard, self.other):
            AccessControl.objects.create(
                team=self.team, resource="dashboard", resource_id=str(dashboard.id), access_level="none"
            )
            AccessControl.objects.create(
                team=self.team,
                resource="dashboard",
                resource_id=str(dashboard.id),
                access_level="editor",
                organization_member=self.organization_membership,
            )

    def _rules_on(self, dashboard: Dashboard) -> int:
        return AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id)).count()

    def test_soft_deleting_an_object_drops_its_rules_only(self) -> None:
        self.dashboard.deleted = True
        self.dashboard.save()

        assert self._rules_on(self.dashboard) == 0
        assert self._rules_on(self.other) == 2

    def test_hard_deleting_an_object_drops_its_rules(self) -> None:
        dashboard_id = self.dashboard.id
        self.dashboard.delete()

        assert not AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard_id)).exists()
        assert self._rules_on(self.other) == 2
