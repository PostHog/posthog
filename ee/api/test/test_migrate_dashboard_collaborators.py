import uuid
from importlib import import_module
from types import SimpleNamespace
from typing import Any

from posthog.test.base import APIBaseTest, NonAtomicBaseTestKeepIdentities
from unittest.mock import patch

from django.db import IntegrityError, connection, router
from django.db.migrations.executor import MigrationExecutor

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User
from posthog.rbac.migrations.rbac_dashboard_migration import rbac_dashboard_access_control_migration

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight


def _scalar(sql: str, params: list) -> object:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return row[0] if row else None


def _conversion_state() -> Any:
    return MigrationExecutor(connection).loader.project_state([("ee", "0065_accesscontrol_limit_resource_access")])


class TestMigrateDashboardCollaborators(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": feature, "name": feature}
            for feature in (AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS)
        ]
        self.organization.save()
        AccessControl.objects.filter(team=self.team, resource="project").delete()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="member"
        )

    def _set_legacy_restriction(self, dashboard: Dashboard, user: User, level: int = 37) -> None:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE posthog_dashboard SET restriction_level = 37 WHERE id = %s", [dashboard.id])
            cursor.execute(
                "INSERT INTO ee_dashboardprivilege (id, dashboard_id, user_id, level, added_at, updated_at)"
                " VALUES (%s, %s, %s, %s, now(), now())",
                [str(uuid.uuid4()), dashboard.id, user.id, level],
            )

    def _run_migration(self) -> None:
        rbac_dashboard_access_control_migration(_conversion_state().apps, SimpleNamespace(connection=connection))

    @parameterized.expand(
        [
            (f"{name}_{mode}", privilege_level, rule_subject, rule_level, most_specific, expected)
            for mode, most_specific in (("legacy", False), ("most_specific", True))
            for name, privilege_level, rule_subject, rule_level, expected in (
                ("viewer", 21, "resource", "editor", "viewer"),
                ("editor", 37, "resource", "editor", "editor"),
                ("non_collaborator", None, "resource", "editor", "viewer"),
                ("member_grant", None, "member", "editor", "viewer"),
                ("role_grant", None, "role", "editor", "viewer"),
                ("collaborator_role_grant", 37, "role", "editor", "editor"),
                ("collaborator_role_denial", 37, "role", "none", "none"),
                ("resource_denial", 21, "resource", "none", "none"),
                ("project_member_override", None, "project", "member", "viewer"),
                ("project_admin_override", None, "project", "admin", "editor"),
            )
        ]
    )
    def test_preserves_effective_access(
        self,
        _name: str,
        privilege_level: int | None,
        rule_subject: str,
        rule_level: str,
        most_specific: bool,
        expected: str,
    ) -> None:
        self.organization.uses_most_specific_access_resolution = most_specific
        self.organization.save()
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        membership = member.organization_memberships.get(organization=self.organization)
        dashboard = Dashboard.objects.create(team=self.team, name="restricted", created_by=self.user)
        self._set_legacy_restriction(dashboard, member, privilege_level or 21)
        if privilege_level is None:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM ee_dashboardprivilege WHERE dashboard_id = %s", [dashboard.id])
        role = None
        if rule_subject == "role":
            role = Role.objects.create(organization=self.organization, name="Analysts")
            RoleMembership.objects.create(role=role, user=member, organization_member=membership)
        if rule_subject == "project":
            AccessControl.objects.filter(team=self.team, resource="project").update(access_level="admin")
        AccessControl.objects.create(
            team=self.team,
            resource="project" if rule_subject == "project" else "dashboard",
            resource_id=(
                str(self.team.id)
                if rule_subject == "project"
                else None
                if rule_subject == "resource"
                else str(dashboard.id)
            ),
            organization_member=membership if rule_subject in ("member", "project") else None,
            role=role,
            access_level=rule_level,
        )

        self._run_migration()
        first_rules = set(
            AccessControl.objects.filter(team=self.team, resource="dashboard").values_list("id", flat=True)
        )
        self._run_migration()

        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [dashboard.id]) == 21
        assert _scalar("SELECT count(*) FROM ee_dashboardprivilege WHERE dashboard_id = %s", [dashboard.id]) == 0
        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) == expected
        assert first_rules == set(
            AccessControl.objects.filter(team=self.team, resource="dashboard").values_list("id", flat=True)
        )
        newcomer = self._create_user("new-member@example.com", level=OrganizationMembership.Level.MEMBER)
        newcomer_level = UserAccessControl(newcomer, team=self.team).get_user_access_level(dashboard)
        assert newcomer_level == ("none" if rule_subject == "resource" and rule_level == "none" else "viewer")

    def test_ignores_restrictions_without_the_entitlement(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        dashboard = Dashboard.objects.create(team=self.team, name="restricted", created_by=self.user)
        self._set_legacy_restriction(dashboard, member, 21)

        self._run_migration()

        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) == "editor"

    def test_skips_collaborators_without_an_organization_membership(self) -> None:
        outsider = User.objects.create_user(email="no-membership@example.com", first_name="", password=None)
        dashboard = Dashboard.objects.create(team=self.team, name="restricted")
        self._set_legacy_restriction(dashboard, outsider)

        self._run_migration()

        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [dashboard.id]) == 21
        assert not AccessControl.objects.filter(
            resource="dashboard", resource_id=str(dashboard.id), organization_member__user=outsider
        ).exists()
        assert _scalar("SELECT count(*) FROM ee_dashboardprivilege WHERE dashboard_id = %s", [dashboard.id]) == 1

    def test_leaves_unrestricted_dashboards_alone(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="open")

        self._run_migration()

        assert not AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id)).exists()

    def test_all_migration_queries_use_the_schema_editors_connection(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="restricted")
        self._set_legacy_restriction(dashboard, self.user)

        with (
            patch.object(router, "db_for_read", side_effect=AssertionError("Unbound migration read")),
            patch.object(router, "db_for_write", side_effect=AssertionError("Unbound migration write")),
        ):
            self._run_migration()

        assert AccessControl.objects.filter(
            team=self.team, resource="dashboard", resource_id=str(dashboard.id)
        ).exists()

    @parameterized.expand([("own_team", False), ("sibling_team", True)])
    def test_migrated_access_gates_dashboard_sharing_and_insight_edits(self, _name: str, sibling: bool) -> None:
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        dashboard = Dashboard.objects.create(team=self.team, name="restricted", created_by=self.user)
        self._set_legacy_restriction(dashboard, member, 21)
        insight = Insight.objects.create(team=self.team, name="chart", created_by=member)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        self._run_migration()
        request_team = (
            Team.objects.create(organization=self.organization, project=self.team.project) if sibling else self.team
        )
        self.client.force_login(member)

        assert self.client.get(f"/api/projects/{request_team.id}/dashboards/{dashboard.id}/").status_code == 200
        assert (
            self.client.patch(
                f"/api/projects/{request_team.id}/dashboards/{dashboard.id}/", {"name": "changed"}
            ).status_code
            == 403
        )
        assert (
            self.client.patch(
                f"/api/projects/{request_team.id}/dashboards/{dashboard.id}/sharing/", {"enabled": True}
            ).status_code
            == 403
        )
        assert (
            self.client.patch(f"/api/projects/{request_team.id}/insights/{insight.id}/", {"deleted": True}).status_code
            == 403
        )
        response = self.client.post(
            f"/api/projects/{request_team.id}/insights/bulk_delete/", {"ids": [insight.id]}, format="json"
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == []
        response = self.client.post(
            f"/api/projects/{request_team.id}/insights/bulk_update_tags/",
            {"ids": [insight.id], "action": "add", "tags": ["reviewed"]},
            format="json",
        )
        assert response.status_code == 403
        insight.refresh_from_db()
        assert not insight.deleted
        dashboard.refresh_from_db()
        assert dashboard.name == "restricted"
        open_dashboard = Dashboard.objects.create(team=self.team, name="open", created_by=self.user)
        DashboardTile.objects.create(dashboard=open_dashboard, insight=insight)
        assert (
            self.client.patch(
                f"/api/projects/{request_team.id}/insights/{insight.id}/", {"name": "changed"}
            ).status_code
            == 200
        )


class TestDashboardConversionTransactions(NonAtomicBaseTestKeepIdentities):
    def test_failed_dashboard_rolls_back_without_undoing_completed_dashboards(self) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        first = Dashboard.objects.create(team=self.team, name="first")
        second = Dashboard.objects.create(team=self.team, name="second")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE posthog_dashboard SET restriction_level = 37 WHERE id IN (%s, %s)", [first.id, second.id]
            )

        def fail_second_dashboard(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
            if sql.startswith("UPDATE posthog_dashboard SET restriction_level") and params[1] == second.id:
                raise IntegrityError("Interrupted dashboard conversion")
            return execute(sql, params, many, context)

        migration = import_module("ee.migrations.0066_migrate_dashboard_collaborators").Migration("0066", "ee")
        with self.assertRaisesMessage(IntegrityError, "Interrupted dashboard conversion"):
            with connection.execute_wrapper(fail_second_dashboard), connection.schema_editor(atomic=False) as editor:
                migration.apply(_conversion_state(), editor)

        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [first.id]) == 21
        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [second.id]) == 37
        assert AccessControl.objects.filter(team=self.team, resource="dashboard", resource_id=str(first.id)).exists()
        assert not AccessControl.objects.filter(
            team=self.team, resource="dashboard", resource_id=str(second.id)
        ).exists()
