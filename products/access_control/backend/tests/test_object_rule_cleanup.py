from posthog.test.base import BaseTest

from django.db.models.deletion import Collector

from posthog.session.models import Session

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

    def test_a_model_that_carries_no_object_rules_keeps_the_fast_delete_path(self) -> None:
        # Receivers connected without a sender answer for every model, and Django then drops the
        # fast-delete path application-wide: the scheduled expired-session cleanup would read every
        # row into memory instead of issuing one DELETE.
        assert Collector(using=Session.objects.db).can_fast_delete(Session.objects.all())
