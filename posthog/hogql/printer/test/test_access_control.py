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

        # Get the dashboards table
        system_node = database.tables.children.get("system")
        dashboards_table = system_node.children.get("dashboards")

        # Create a mock table type
        table_type = ast.TableType(table=dashboards_table)

        guard = build_access_control_guard(dashboards_table, table_type, context)
        assert guard is None

    def test_build_access_control_guard_returns_none_without_user(self):
        """Without user context, no guard should be generated."""
        context = HogQLContext(team_id=self.team.pk, team=self.team, user=None)
        database = Database.create_for(team=self.team, user=None)
        context.database = database

        # Get the dashboards table
        system_node = database.tables.children.get("system")
        dashboards_table = system_node.children.get("dashboards")

        # Create a mock table type
        table_type = ast.TableType(table=dashboards_table)

        guard = build_access_control_guard(dashboards_table, table_type, context)
        assert guard is None


class TestAccessControlIntegration(BaseTest):
    """Integration tests for access control in HogQL queries."""

    def _compile_select(self, query: str, context: HogQLContext) -> str:
        """Helper to compile a HogQL query to ClickHouse SQL."""
        from posthog.hogql.parser import parse_select

        node = parse_select(query)
        prepared = prepare_ast_for_printing(node, context=context, dialect="clickhouse")
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
