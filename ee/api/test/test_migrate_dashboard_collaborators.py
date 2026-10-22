import uuid
from collections.abc import Iterator
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

from products.access_control.backend.facade.user_access_control import DASHBOARD_EDIT_LIMIT_RESOURCE, UserAccessControl
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
    return MigrationExecutor(connection).loader.project_state([("ee", "0064_split_identity_provider_config_scopes")])


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
        original_rule = AccessControl.objects.create(
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
        first_rules = set(AccessControl.objects.filter(team=self.team).values_list("id", flat=True))
        self._run_migration()

        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [dashboard.id]) == 37
        assert _scalar("SELECT count(*) FROM ee_dashboardprivilege WHERE dashboard_id = %s", [dashboard.id]) == (
            0 if privilege_level is None else 1
        )
        assert (
            _scalar("SELECT level FROM ee_dashboardprivilege WHERE dashboard_id = %s", [dashboard.id])
            == privilege_level
        )
        assert AccessControl.objects.filter(id=original_rule.id, access_level=rule_level).exists()
        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) == expected
        assert first_rules == set(AccessControl.objects.filter(team=self.team).values_list("id", flat=True))
        newcomer = self._create_user("new-member@example.com", level=OrganizationMembership.Level.MEMBER)
        newcomer_level = UserAccessControl(newcomer, team=self.team).get_user_access_level(dashboard)
        assert newcomer_level == (
            "editor"
            if rule_subject == "project"
            else "none"
            if rule_subject == "resource" and rule_level == "none"
            else "viewer"
        )

    @parameterized.expand([("legacy", False), ("most_specific", True)])
    def test_private_defaults_still_deny_new_members(self, _name: str, most_specific: bool) -> None:
        self.organization.uses_most_specific_access_resolution = most_specific
        self.organization.save()
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self._set_legacy_restriction(dashboard, self.user)
        denial = AccessControl.objects.create(
            team=self.team, resource="dashboard", resource_id=str(dashboard.id), access_level="none"
        )

        self._run_migration()
        newcomer = self._create_user("new-member@example.com", level=OrganizationMembership.Level.MEMBER)

        assert UserAccessControl(newcomer, team=self.team).get_user_access_level(dashboard) == "none"
        denial.refresh_from_db()
        assert denial.access_level == "none"

    @parameterized.expand(
        [
            (f"{mode}_{scope}", most_specific, scope)
            for mode, most_specific in (("legacy", False), ("most_specific", True))
            for scope in ("object", "resource")
        ]
    )
    def test_role_grants_remain_revocable(self, _name: str, most_specific: bool, scope: str) -> None:
        self.organization.uses_most_specific_access_resolution = most_specific
        self.organization.save()
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        membership = member.organization_memberships.get(organization=self.organization)
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self._set_legacy_restriction(dashboard, member)
        role = Role.objects.create(organization=self.organization, name="Analysts")
        role_membership = RoleMembership.objects.create(role=role, user=member, organization_member=membership)
        resource_id = str(dashboard.id) if scope == "object" else None
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id=resource_id, access_level="none")
        grant = AccessControl.objects.create(
            team=self.team, resource="dashboard", resource_id=resource_id, access_level="editor", role=role
        )

        self._run_migration()
        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) == "editor"
        role_membership.delete()

        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) == "none"
        assert AccessControl.objects.filter(id=grant.id, role=role).exists()
        assert not AccessControl.objects.filter(
            team=self.team, resource="dashboard", organization_member=membership
        ).exists()

    @parameterized.expand(
        [("dashboard", "invalid", "viewer"), ("dashboard", "", "viewer"), ("project", "invalid", "none")]
    )
    def test_repairs_invalid_access_levels(self, resource: str, invalid: str, expected: str) -> None:
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self._set_legacy_restriction(dashboard, member)
        if resource == "project":
            rule = AccessControl.objects.get(team=self.team, resource="project", resource_id=str(self.team.id))
            rule.access_level = invalid
            rule.save(update_fields=["access_level"])
        else:
            rule = AccessControl.objects.create(
                team=self.team, resource="dashboard", resource_id=str(dashboard.id), access_level=invalid
            )

        self._run_migration()

        rule.refresh_from_db()
        assert rule.access_level == expected
        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) in ("viewer", "editor")

    @parameterized.expand([("override", "editor", "editor"), ("remove", None, "viewer")])
    def test_replacing_default_removes_the_migrated_limit(self, _name: str, level: str | None, expected: str) -> None:
        self.organization.uses_most_specific_access_resolution = True
        self.organization.save()
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self._set_legacy_restriction(dashboard, self.user)
        AccessControl.objects.create(team=self.team, resource="dashboard", access_level="viewer")
        AccessControl.objects.create(
            team=self.team, resource="dashboard", resource_id=str(dashboard.id), access_level="viewer"
        )
        self._run_migration()
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) == "viewer"

        admin = self._create_user("admin@example.com", level=OrganizationMembership.Level.ADMIN)
        self.client.force_login(admin)
        response = self.client.put(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/access_controls/",
            {"access_level": level},
            format="json",
        )
        assert response.status_code == (204 if level is None else 200), response.data
        self._run_migration()
        newcomer = self._create_user("new-member@example.com", level=OrganizationMembership.Level.MEMBER)
        access = UserAccessControl(newcomer, team=self.team)

        assert access.get_user_access_level(dashboard) == expected
        assert not access.has_object_access_limit("dashboard", str(dashboard.id))

    @parameterized.expand([("member", False), ("member", True), ("role", False), ("role", True)])
    def test_explicit_subject_grants_replace_the_migrated_limit(self, subject: str, most_specific: bool) -> None:
        self.organization.uses_most_specific_access_resolution = most_specific
        self.organization.save()
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        membership = member.organization_memberships.get(organization=self.organization)
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self._set_legacy_restriction(dashboard, member, 21)
        AccessControl.objects.create(
            team=self.team, resource="dashboard", resource_id=str(dashboard.id), access_level="none"
        )
        self._run_migration()
        payload: dict[str, str | None] = {"access_level": "editor", "organization_member": str(membership.id)}
        role_membership = None
        if subject == "role":
            role = Role.objects.create(organization=self.organization, name="Editors")
            role_membership = RoleMembership.objects.create(role=role, user=member, organization_member=membership)
            payload = {"access_level": "editor", "role": str(role.id)}
        admin = self._create_user("admin@example.com", level=OrganizationMembership.Level.ADMIN)
        self.client.force_login(admin)

        response = self.client.put(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/access_controls/", payload, format="json"
        )
        assert response.status_code == 200, response.data
        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) == "editor"
        if role_membership is not None:
            role_membership.delete()
        else:
            payload["access_level"] = None
            response = self.client.put(
                f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/access_controls/", payload, format="json"
            )
            assert response.status_code == 204, response.data
        assert UserAccessControl(member, team=self.team).get_user_access_level(dashboard) == "none"

    def test_edit_limit_lookup_indexes_rows_once(self) -> None:
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self._set_legacy_restriction(dashboard, member, 21)
        self._run_migration()

        class CountedRows(list[AccessControl]):
            iterations = 0

            def __iter__(self) -> Iterator[AccessControl]:
                self.iterations += 1
                return super().__iter__()

        rows = CountedRows(AccessControl.objects.filter(team=self.team))
        access = UserAccessControl(member, team=self.team)
        access.__dict__["_cached_access_controls"] = rows
        for _ in range(20):
            assert access.has_object_access_limit("dashboard", str(dashboard.id))
            assert not access.has_object_access_limit("dashboard", "unrestricted")
        assert rows.iterations == 1

        admin_rows = CountedRows(rows)
        admin = self._create_user("admin@example.com", level=OrganizationMembership.Level.ADMIN)
        admin_access = UserAccessControl(admin, team=self.team)
        admin_access.__dict__["_cached_access_controls"] = admin_rows
        assert not admin_access.has_object_access_limit("dashboard", str(dashboard.id))
        assert admin_rows.iterations == 0

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

        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [dashboard.id]) == 37
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
            team=self.team, resource=DASHBOARD_EDIT_LIMIT_RESOURCE, resource_id=str(dashboard.id)
        ).exists()

    @parameterized.expand(
        [
            (f"{scope}_{mode}_{project_access}", sibling, most_specific, project_access)
            for scope, sibling in (("own_team", False), ("sibling_team", True))
            for mode, most_specific in (("legacy", False), ("most_specific", True))
            for project_access in ("member", None)
        ]
    )
    def test_migrated_access_gates_dashboard_sharing_and_insight_edits(
        self, _name: str, sibling: bool, most_specific: bool, project_access: str | None
    ) -> None:
        self.organization.uses_most_specific_access_resolution = most_specific
        self.organization.save()
        if project_access is None:
            AccessControl.objects.filter(team=self.team, resource="project").delete()
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        dashboard = Dashboard.objects.create(team=self.team, name="restricted", created_by=self.user)
        self._set_legacy_restriction(dashboard, member, 21)
        insight = Insight.objects.create(team=self.team, name="chart", created_by=member)
        restricted_tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        open_dashboard = Dashboard.objects.create(team=self.team, name="open", created_by=self.user)
        removed_tile = DashboardTile.objects.create(dashboard=open_dashboard, insight=insight, deleted=True)
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
        removed_tile.deleted = False
        removed_tile.save(update_fields=["deleted"])
        assert (
            self.client.patch(
                f"/api/projects/{request_team.id}/insights/{insight.id}/", {"name": "changed"}
            ).status_code
            == 200
        )

        response = self.client.post(
            f"/api/projects/{request_team.id}/insights/bulk_delete/", {"ids": [insight.id]}, format="json"
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["deleted"]] == [insight.id]
        response = self.client.post(
            f"/api/projects/{request_team.id}/insights/bulk_restore/", {"ids": [insight.id]}, format="json"
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["restored"]] == [insight.id]
        restricted_tile.refresh_from_db()
        removed_tile.refresh_from_db()
        assert restricted_tile.deleted is True
        assert removed_tile.deleted is False

        response = self.client.patch(
            f"/api/projects/{request_team.id}/insights/{insight.id}/", {"dashboards": []}, format="json"
        )
        assert response.status_code == 200
        assert not DashboardTile.objects.filter(insight=insight).exists()
        assert (
            self.client.patch(
                f"/api/projects/{request_team.id}/insights/{insight.id}/", {"name": "unauthorized"}
            ).status_code
            == 403
        )
        response = self.client.post(
            f"/api/projects/{request_team.id}/insights/bulk_delete/", {"ids": [insight.id]}, format="json"
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == []
        self.client.force_login(self.user)
        assert (
            self.client.patch(
                f"/api/projects/{request_team.id}/insights/{insight.id}/", {"name": "authorized"}
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
            if (
                sql.startswith('INSERT INTO "ee_accesscontrol"')
                and DASHBOARD_EDIT_LIMIT_RESOURCE in params
                and str(second.id) in params
            ):
                raise IntegrityError("Interrupted dashboard conversion")
            return execute(sql, params, many, context)

        migration = import_module("ee.migrations.0065_migrate_dashboard_collaborators").Migration("0065", "ee")
        with self.assertRaisesMessage(IntegrityError, "Interrupted dashboard conversion"):
            with connection.execute_wrapper(fail_second_dashboard), connection.schema_editor(atomic=False) as editor:
                migration.apply(_conversion_state(), editor)

        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [first.id]) == 37
        assert _scalar("SELECT restriction_level FROM posthog_dashboard WHERE id = %s", [second.id]) == 37
        assert AccessControl.objects.filter(
            team=self.team, resource=DASHBOARD_EDIT_LIMIT_RESOURCE, resource_id=str(first.id)
        ).exists()
        assert not AccessControl.objects.filter(
            team=self.team, resource=DASHBOARD_EDIT_LIMIT_RESOURCE, resource_id=str(second.id)
        ).exists()
