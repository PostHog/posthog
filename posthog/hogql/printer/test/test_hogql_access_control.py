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
        assert "activity_logs" not in system_node.children
        assert "dashboards" not in system_node.children
        assert "insights" not in system_node.children
        assert "experiments" not in system_node.children
        assert "feature_flags" not in system_node.children
        assert "surveys" not in system_node.children
        assert "annotations" not in system_node.children
        assert "data_warehouse_sources" not in system_node.children
        assert "actions" not in system_node.children
        assert "hog_flows" not in system_node.children
        assert "notebooks" not in system_node.children
        assert "error_tracking_issues" not in system_node.children
        assert "support_tickets" not in system_node.children
        # But tracked in denied list for clear error messages
        assert "system.activity_logs" in database._denied_tables
        assert "system.dashboards" in database._denied_tables
        assert "system.insights" in database._denied_tables
        assert "system.experiments" in database._denied_tables
        assert "system.feature_flags" in database._denied_tables
        assert "system.surveys" in database._denied_tables
        assert "system.annotations" in database._denied_tables
        assert "system.data_warehouse_sources" in database._denied_tables
        assert "system.actions" in database._denied_tables
        assert "system.hog_flows" in database._denied_tables
        assert "system.notebooks" in database._denied_tables
        assert "system.error_tracking_issues" in database._denied_tables
        assert "system.support_tickets" in database._denied_tables
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

        # Enable access control feature
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
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


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestWarehouseTableAccessControl(BaseTest):
    """Per-object access control for warehouse tables.

    Each DataWarehouseTable row is treated as an object of the warehouse_table
    resource (with warehouse_objects as the inheritance parent). The HogQL
    decision uses the same UserAccessControl.check_access_level_for_object
    primitive as the warehouse_table REST API.
    """

    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
        from products.warehouse_sources.backend.models.table import DataWarehouseTable

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        self.credential = DataWarehouseCredential.objects.create(
            access_key="blah", access_secret="blah", team=self.team
        )
        self.allowed_table = DataWarehouseTable.objects.create(
            name="allowed_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="s3://bucket/allowed/*",
            columns={"id": "String"},
        )
        self.denied_table = DataWarehouseTable.objects.create(
            name="denied_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="s3://bucket/denied/*",
            columns={"id": "String"},
        )

    def _create_ac(self, *, resource, access_level, resource_id=None, role=None, member=None):
        from ee.models.rbac.access_control import AccessControl

        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=member,
            role=role,
        )

    def _membership(self):
        return OrganizationMembership.objects.get(user=self.user, organization=self.organization)

    def test_explicit_object_level_deny_marks_table(self):
        # Member-scoped per-object deny on denied_table; allowed_table should still resolve.
        self._create_ac(
            resource="warehouse_table",
            resource_id=str(self.denied_table.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user)

        assert "denied_table" in database._denied_tables
        assert "allowed_table" not in database._denied_tables
        assert str(self.denied_table.id) in database._denied_resource_ids_by_scope.get("warehouse_table", set())

    def test_warehouse_objects_resource_none_denies_all_tables(self):
        self._create_ac(resource="warehouse_objects", access_level="none")

        database = Database.create_for(team=self.team, user=self.user)

        # Both tables become inaccessible because warehouse_table inherits warehouse_objects
        assert "denied_table" in database._denied_tables
        assert "allowed_table" in database._denied_tables

    def test_warehouse_objects_resource_none_plus_specific_member_grant(self):
        # User has no warehouse_objects access, but has explicit viewer on allowed_table.
        self._create_ac(resource="warehouse_objects", access_level="none")
        self._create_ac(
            resource="warehouse_table",
            resource_id=str(self.allowed_table.id),
            access_level="viewer",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user)

        # Specific grant wins: allowed_table is reachable, denied_table is not.
        assert "allowed_table" not in database._denied_tables
        assert "denied_table" in database._denied_tables

    def test_org_admin_bypasses_warehouse_acl(self):
        membership = self._membership()
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        # Even with a deny row, org admins keep access
        self._create_ac(
            resource="warehouse_table",
            resource_id=str(self.denied_table.id),
            access_level="none",
            member=membership,
        )

        database = Database.create_for(team=self.team, user=self.user)

        assert "denied_table" not in database._denied_tables
        assert "allowed_table" not in database._denied_tables

    def test_no_user_fails_closed_for_warehouse_tables(self):
        database = Database.create_for(team=self.team, user=None)

        assert "denied_table" in database._denied_tables
        assert "allowed_table" in database._denied_tables

    def test_bypass_access_control_skips_warehouse_acl(self):
        self._create_ac(
            resource="warehouse_table",
            resource_id=str(self.denied_table.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user, bypass_access_control=True)

        assert "denied_table" not in database._denied_tables
        assert "allowed_table" not in database._denied_tables

    def test_bypass_access_control_skips_warehouse_acl_without_user(self):
        # The classic background-job case: no user, but the caller explicitly opts in.
        database = Database.create_for(team=self.team, user=None, bypass_access_control=True)

        assert "denied_table" not in database._denied_tables
        assert "allowed_table" not in database._denied_tables

    def test_denied_table_lookup_raises_access_error(self):
        from posthog.hogql.errors import QueryError

        self._create_ac(
            resource="warehouse_table",
            resource_id=str(self.denied_table.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user)

        with self.assertRaises(QueryError) as cm:
            database.get_table("denied_table")
        assert "don't have access" in str(cm.exception)
        assert "Unknown" not in str(cm.exception)


class TestWarehouseTableAccessControlFlagOff(BaseTest):
    """Regression guard: with hogql-warehouse-access-control off, nothing is filtered."""

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
        from products.warehouse_sources.backend.models.table import DataWarehouseTable

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        credential = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        self.table = DataWarehouseTable.objects.create(
            name="some_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=credential,
            url_pattern="s3://bucket/some_table/*",
            columns={"id": "String"},
        )

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
    def test_warehouse_table_acl_off_keeps_all_tables(self):
        from ee.models.rbac.access_control import AccessControl

        # Even an explicit deny row should be ignored when the FF is off.
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(self.table.id),
            access_level="none",
            organization_member=membership,
        )

        database = Database.create_for(team=self.team, user=self.user)

        assert "some_table" not in database._denied_tables
        assert not database._denied_resource_ids_by_scope.get("warehouse_table")


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestWarehouseViewAccessControl(BaseTest):
    """Per-object access control for warehouse saved queries (DataWarehouseSavedQuery)."""

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        self.allowed_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="allowed_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"},
            columns={"id": "String"},
        )
        self.denied_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="denied_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"},
            columns={"id": "String"},
        )

    def _create_ac(self, *, resource, access_level, resource_id=None, role=None, member=None):
        from ee.models.rbac.access_control import AccessControl

        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=member,
            role=role,
        )

    def _membership(self):
        return OrganizationMembership.objects.get(user=self.user, organization=self.organization)

    def test_explicit_object_level_deny_marks_saved_query(self):
        self._create_ac(
            resource="warehouse_view",
            resource_id=str(self.denied_view.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user)

        assert "denied_view" in database._denied_tables
        assert "allowed_view" not in database._denied_tables
        assert str(self.denied_view.id) in database._denied_resource_ids_by_scope.get("warehouse_view", set())

    def test_warehouse_objects_resource_none_denies_all_views(self):
        self._create_ac(resource="warehouse_objects", access_level="none")

        database = Database.create_for(team=self.team, user=self.user)

        assert "denied_view" in database._denied_tables
        assert "allowed_view" in database._denied_tables

    def test_no_user_fails_closed_for_warehouse_views(self):
        database = Database.create_for(team=self.team, user=None)

        assert "denied_view" in database._denied_tables
        assert "allowed_view" in database._denied_tables

    def test_bypass_access_control_skips_warehouse_view_acl(self):
        self._create_ac(
            resource="warehouse_view",
            resource_id=str(self.denied_view.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user, bypass_access_control=True)

        assert "denied_view" not in database._denied_tables
        assert "allowed_view" not in database._denied_tables
