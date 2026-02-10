from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.printer.access_control import build_access_control_guard, get_blocked_resource_ids

from posthog.models import OrganizationMembership


class TestAccessControlSystemTables(BaseTest):
    """Test resource-level access control for system tables."""

    def test_org_admin_gets_all_system_tables(self):
        """Org admins should have access to all system tables."""
        # Make user an org admin
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        database = Database.create_for(team=self.team, user=self.user)

        # Check that system tables are available
        system_node = database.tables.children.get("system")
        assert system_node is not None
        assert hasattr(system_node, "children")
        # All system tables should be present for admin
        assert "dashboards" in system_node.children
        assert "insights" in system_node.children
        assert "experiments" in system_node.children
        assert "feature_flags" in system_node.children
        assert "surveys" in system_node.children

    def test_regular_user_with_full_access_gets_all_tables(self):
        """Regular users with default full access should see all tables."""
        # Default setup - user has no restrictions
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        database = Database.create_for(team=self.team, user=self.user)

        # System tables should still be available with default access
        system_node = database.tables.children.get("system")
        assert system_node is not None

    def test_database_without_user_returns_all_tables(self):
        """Without user context, all tables should be available (backwards compat)."""
        database = Database.create_for(team=self.team, user=None)

        # All system tables should be present
        system_node = database.tables.children.get("system")
        assert system_node is not None


class TestAccessControlGuard(BaseTest):
    """Test object-level access control guard generation."""

    def _get_dashboards_table(self, database: Database):
        from posthog.hogql.database.postgres_table import PostgresTable

        system_node = database.tables.children.get("system")
        assert system_node is not None
        dashboards_node = system_node.children.get("dashboards")
        assert dashboards_node is not None
        table = dashboards_node.get()
        assert isinstance(table, PostgresTable)
        return table

    def test_get_blocked_resource_ids_empty_for_admin(self):
        """Org admins should have no blocked IDs."""
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        context = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user)

        blocked_ids = get_blocked_resource_ids("dashboard", context)
        assert blocked_ids == set()

    def test_get_blocked_resource_ids_empty_without_user(self):
        """Without user context, no IDs should be blocked."""
        context = HogQLContext(team_id=self.team.pk, team=self.team, user=None)

        blocked_ids = get_blocked_resource_ids("dashboard", context)
        assert blocked_ids == set()

    def test_build_access_control_guard_returns_none_for_admin(self):
        """Org admins should not have an access control guard."""
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        context = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user)
        database = Database.create_for(team=self.team, user=self.user)
        context.database = database

        table = self._get_dashboards_table(database)
        table_type = ast.TableType(table=table)

        guard = build_access_control_guard(table, table_type, context)
        assert guard is None

    def test_build_access_control_guard_returns_none_without_user(self):
        """Without user context, no guard should be generated."""
        context = HogQLContext(team_id=self.team.pk, team=self.team, user=None)
        database = Database.create_for(team=self.team, user=None)
        context.database = database

        table = self._get_dashboards_table(database)
        table_type = ast.TableType(table=table)

        guard = build_access_control_guard(table, table_type, context)
        assert guard is None


class TestObjectLevelAccessControl(BaseTest):
    """Test object-level access control (get_blocked_resource_ids)."""

    def _setup_permissions(self):
        from posthog.constants import AvailableFeature

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()

        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.membership.level = OrganizationMembership.Level.MEMBER
        self.membership.save()

        self.database = Database.create_for(team=self.team, user=self.user)
        self.context = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user)
        self.context.database = self.database

    def test_no_object_overrides_means_no_blocked_ids(self):
        """If there are no object-level AC entries, nothing is blocked (resource-level already passed)."""
        self._setup_permissions()

        blocked = get_blocked_resource_ids("dashboard", self.context)
        assert blocked == set()

    def test_object_default_none_blocks_object(self):
        """Object-level default 'none' with no member/role override blocks the object."""
        from ee.models import AccessControl

        self._setup_permissions()

        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
        )

        blocked = get_blocked_resource_ids("dashboard", self.context)
        assert "42" in blocked

    def test_object_default_editor_allows_object(self):
        """Object-level default 'editor' means the object is accessible."""
        from ee.models import AccessControl

        self._setup_permissions()

        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="editor",
        )

        blocked = get_blocked_resource_ids("dashboard", self.context)
        assert "42" not in blocked

    def test_object_default_none_with_member_editor_override_allows(self):
        """Object default 'none' but member-specific 'editor' override → allowed (highest wins)."""
        from ee.models import AccessControl

        self._setup_permissions()

        # Team-wide default: no access
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
        )
        # Member-specific override: editor access
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="editor",
            organization_member=self.membership,
        )

        blocked = get_blocked_resource_ids("dashboard", self.context)
        assert "42" not in blocked

    def test_object_default_editor_with_member_none_still_allows(self):
        """Object default 'editor' + member 'none' can't happen in app, but if it does, highest wins."""
        from ee.models import AccessControl

        self._setup_permissions()

        # Team-wide default: editor access
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="editor",
        )
        # Member-specific override: none (shouldn't happen in app, but test anyway)
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
            organization_member=self.membership,
        )

        blocked = get_blocked_resource_ids("dashboard", self.context)
        assert "42" not in blocked

    def test_multiple_objects_mixed_access(self):
        """Multiple objects: some blocked, some allowed."""
        from ee.models import AccessControl

        self._setup_permissions()

        # Dashboard 10: blocked (default none, no overrides)
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id="10", access_level="none")
        # Dashboard 20: allowed (default editor)
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id="20", access_level="editor")
        # Dashboard 30: allowed (default none + member editor)
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id="30", access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="30",
            access_level="editor",
            organization_member=self.membership,
        )

        blocked = get_blocked_resource_ids("dashboard", self.context)
        assert blocked == {"10"}


class TestDeniedTableError(BaseTest):
    """Test that denied tables show a helpful error message."""

    def test_denied_table_shows_access_error(self):
        """When a table is denied, error should say 'no access' not 'unknown'."""
        from posthog.hogql.errors import QueryError

        from posthog.constants import AvailableFeature

        from ee.models import AccessControl

        # Enable advanced permissions feature
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()

        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        # Explicitly deny dashboard access
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            access_level="none",
        )

        database = Database.create_for(team=self.team, user=self.user)

        # Verify the table is in denied list
        assert "system.dashboards" in database._denied_tables

        # Try to get the table and verify error message
        with self.assertRaises(QueryError) as cm:
            database.get_table("system.dashboards")

        assert "don't have access" in str(cm.exception)
        assert "Unknown" not in str(cm.exception)

    def test_unknown_table_still_shows_unknown_error(self):
        """Tables that don't exist should still show 'unknown' error."""
        from posthog.hogql.errors import QueryError

        database = Database.create_for(team=self.team, user=self.user)

        with self.assertRaises(QueryError) as cm:
            database.get_table("system.nonexistent_table")

        assert "Unknown table" in str(cm.exception)


class TestAccessControlIntegration(BaseTest):
    """Integration tests for access control in HogQL queries."""

    def _compile_select(self, query: str, context: HogQLContext) -> str:
        """Helper to compile a HogQL query to ClickHouse SQL."""
        from posthog.hogql.parser import parse_select

        node = parse_select(query)
        prepared = prepare_ast_for_printing(node, context=context, dialect="clickhouse")
        assert prepared is not None
        return print_prepared_ast(prepared, context=context, dialect="clickhouse")

    def test_admin_can_query_system_dashboards(self):
        """Admin users should be able to query system.dashboards without restrictions."""
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=self.user,
            enable_select_queries=True,
        )

        # Should compile without errors
        sql = self._compile_select("SELECT id, name FROM system.dashboards", context)
        # Should not have complex access control WHERE clauses
        assert "id" in sql
        assert "name" in sql

    def test_query_without_user_compiles(self):
        """Queries without user context should compile (backwards compatibility)."""
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=None,
            enable_select_queries=True,
        )

        # Should compile without errors
        sql = self._compile_select("SELECT id, name FROM system.dashboards", context)
        assert "id" in sql
        assert "name" in sql
