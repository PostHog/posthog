import uuid
from types import SimpleNamespace

from posthog.test.base import BaseTest

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.rbac.migrations.rbac_dashboard_migration import rbac_dashboard_access_control_migration

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard import Dashboard


def _scalar(sql: str, params: list) -> object:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return row[0] if row else None


class TestMigrateDashboardCollaborators(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

    def _set_legacy_restriction(self, dashboard: Dashboard, user: User) -> None:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE posthog_dashboard SET restriction_level = 37 WHERE id = %s", [dashboard.id])
            cursor.execute(
                "INSERT INTO ee_dashboardprivilege (id, dashboard_id, user_id, level, added_at, updated_at)"
                " VALUES (%s, %s, %s, 37, now(), now())",
                [str(uuid.uuid4()), dashboard.id, user.id],
            )

    def _controls(self, dashboard: Dashboard) -> set[tuple[str, object]]:
        return set(
            AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id)).values_list(
                "access_level", "organization_member_id"
            )
        )

    def _run_migration(self) -> None:
        apps = (
            MigrationExecutor(connection)
            .loader.project_state([("ee", "0064_split_identity_provider_config_scopes")])
            .apps
        )
        rbac_dashboard_access_control_migration(apps, SimpleNamespace(connection=connection))

    def test_converts_restricted_dashboard_and_its_privileges(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="restricted")
        self._set_legacy_restriction(dashboard, self.user)

        self._run_migration()

        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [dashboard.id]) == 21
        assert _scalar("SELECT count(*) FROM ee_dashboardprivilege WHERE dashboard_id = %s", [dashboard.id]) == 0
        assert self._controls(dashboard) == {
            ("viewer", None),
            ("editor", self.organization_membership.id),
        }

    def test_skips_collaborators_without_an_organization_membership(self) -> None:
        outsider = User.objects.create_user(email="no-membership@posthog.com", first_name="", password=None)
        dashboard = Dashboard.objects.create(team=self.team, name="restricted")
        self._set_legacy_restriction(dashboard, outsider)

        self._run_migration()

        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [dashboard.id]) == 21
        # The default viewer rule is created, but no editor rule for the outsider, and their
        # privilege row is left in place.
        assert self._controls(dashboard) == {("viewer", None)}
        assert _scalar("SELECT count(*) FROM ee_dashboardprivilege WHERE dashboard_id = %s", [dashboard.id]) == 1

    def test_leaves_unrestricted_dashboards_alone(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="open")

        self._run_migration()

        assert not self._controls(dashboard)
