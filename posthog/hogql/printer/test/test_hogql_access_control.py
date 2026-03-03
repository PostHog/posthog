from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast

from posthog.models import OrganizationMembership


class TestAccessControlSystemTables(BaseTest):
    """Test resource-level access control for system tables."""

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_org_admin_gets_all_system_tables(self):
        """Org admins should have access to all system tables."""
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        database = Database.create_for(team=self.team, user=self.user)

        system_node = database.tables.children.get("system")
        assert system_node is not None
        fresh_system = SystemTables()
        for table_name in fresh_system.children:
            assert table_name in system_node.children, f"{table_name} missing for admin"

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
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

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_database_without_user_denies_scoped_tables(self):
        """Without user context, scoped tables should be removed and denied (fail-closed)."""
        database = Database.create_for(team=self.team, user=None)

        system_node = database.tables.children.get("system")
        assert system_node is not None
        # Scoped tables removed from schema
        assert "dashboards" not in system_node.children
        assert "insights" not in system_node.children
        assert "experiments" not in system_node.children
        assert "feature_flags" not in system_node.children
        assert "surveys" not in system_node.children
        assert "data_warehouse_sources" not in system_node.children
        assert "actions" not in system_node.children
        assert "notebooks" not in system_node.children
        assert "error_tracking_issues" not in system_node.children
        # But tracked in denied list for clear error messages
        assert "system.dashboards" in database._denied_tables
        assert "system.insights" in database._denied_tables
        assert "system.experiments" in database._denied_tables
        assert "system.feature_flags" in database._denied_tables
        assert "system.surveys" in database._denied_tables
        assert "system.data_warehouse_sources" in database._denied_tables
        assert "system.actions" in database._denied_tables
        assert "system.notebooks" in database._denied_tables
        assert "system.error_tracking_issues" in database._denied_tables
        # Unscoped tables remain
        assert "cohorts" in system_node.children
        assert "teams" in system_node.children


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
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

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
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

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_query_without_user_fails_on_scoped_table(self):
        """Querying a scoped system table without user should fail with access error."""
        from posthog.hogql.errors import QueryError

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=None,
            enable_select_queries=True,
        )

        with self.assertRaises(QueryError) as cm:
            self._compile_select("SELECT id, name FROM system.dashboards", context)
        assert "don't have access" in str(cm.exception)

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
    def test_database_without_user_keeps_all_tables_when_flag_off(self):
        """When the feature flag is off, no tables are denied even without user."""
        database = Database.create_for(team=self.team, user=None)
        assert len(database._denied_tables) == 0
        # Verify against a fresh SystemTables instance to avoid shared-state issues
        fresh_system = SystemTables()
        system_node = database.tables.children.get("system")
        assert system_node is not None
        for table_name in fresh_system.children:
            assert table_name in system_node.children, f"{table_name} missing from system tables when flag is off"

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_query_without_user_works_for_unscoped_tables(self):
        """Unscoped system tables should still be queryable without user context."""
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=None,
            enable_select_queries=True,
        )

        sql = self._compile_select("SELECT id, name FROM system.cohorts", context)
        assert "id" in sql
        assert "name" in sql
