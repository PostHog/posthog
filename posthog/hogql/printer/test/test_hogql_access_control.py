from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.printer.access_control import build_access_control_guard

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import OrganizationMembership, User
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.shared_link_user import SharedLinkUser
from posthog.synthetic_user import SyntheticUser


class TestAccessControlSystemTables(BaseTest):
    """Test resource-level access control for system tables."""

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

    def test_bypass_warehouse_access_control_still_applies_system_table_acl(self):
        """bypass_warehouse_access_control only relaxes warehouse tables/views; scoped system tables
        still fail closed without a user."""
        database = Database.create_for(team=self.team, user=None, bypass_warehouse_access_control=True)

        system_node = database.tables.children.get("system")
        assert system_node is not None
        # Scoped system tables stay denied despite the warehouse bypass.
        assert "dashboards" not in system_node.children
        assert "system.dashboards" in database._denied_tables
        # Unscoped tables remain.
        assert "cohorts" in system_node.children


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
        from posthog.hogql.database.schema.system import dashboards

        context = HogQLContext(team_id=self.team.pk, team=self.team, user=None)
        database = Database.create_for(team=self.team, user=None)
        context.database = database

        table_type = ast.TableType(table=dashboards)

        guard = build_access_control_guard(dashboards, table_type, context)
        assert guard is None

    def test_blocked_ids_bind_as_single_sensitive_placeholder(self):
        """
        The deny list compiles to one ``%(..._sensitive)s`` placeholder bound to a list,
        not N per-ID placeholders. Mirrors ``JSONDropKeys`` in property-level AC.
        """
        from posthog.hogql.parser import parse_select

        from posthog.clickhouse.client.escape import substitute_params_for_display
        from posthog.constants import AvailableFeature

        from ee.models import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        for resource_id in ("dash-1", "dash-2", "dash-3"):
            AccessControl.objects.create(
                team=self.team,
                resource="dashboard",
                resource_id=resource_id,
                access_level="none",
            )

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=self.user,
            enable_select_queries=True,
        )
        prepared = prepare_ast_for_printing(
            parse_select("SELECT id, name FROM system.dashboards"),
            context=context,
            dialect="clickhouse",
        )
        assert prepared is not None
        sql = print_prepared_ast(prepared, context=context, dialect="clickhouse")

        sensitive_keys = [k for k in context.values if k.endswith("_sensitive")]
        deny_keys = [k for k in sensitive_keys if isinstance(context.values[k], list)]
        assert len(deny_keys) == 1, f"expected exactly one sensitive list placeholder, got {sensitive_keys!r}"
        deny_key = deny_keys[0]
        assert context.values[deny_key] == ["dash-1", "dash-2", "dash-3"]
        assert f"notIn(toString(system__dashboards.id), %({deny_key})s)" in sql
        # No raw IDs leaked into the SQL template
        for raw in ("'dash-1'", "'dash-2'", "'dash-3'"):
            assert raw not in sql

        # And the display renderer scrubs them.
        rendered = substitute_params_for_display(sql, context.values)
        for raw in ("dash-1", "dash-2", "dash-3"):
            assert raw not in rendered
        assert "[HIDDEN]" in rendered

    def test_filtering_records_restricted_resource(self):
        # The guard silently drops rows in SQL; recording the resource is what lets the response warn
        # that results may be partial. Regression guard for the context recording.
        from posthog.hogql.parser import parse_select

        from posthog.constants import AvailableFeature

        from ee.models import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id="dash-1", access_level="none")

        context = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True)
        prepared = prepare_ast_for_printing(
            parse_select("SELECT id FROM system.dashboards"), context=context, dialect="clickhouse"
        )
        assert prepared is not None
        print_prepared_ast(prepared, context=context, dialect="clickhouse")

        assert context.access_control_restricted_resources == {"dashboard"}

    def test_no_warning_when_nothing_filtered(self):
        # Admins have no deny set, so no guard and no warning - otherwise every query would nag.
        from posthog.hogql.parser import parse_select

        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        context = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True)
        prepared = prepare_ast_for_printing(
            parse_select("SELECT id FROM system.dashboards"), context=context, dialect="clickhouse"
        )
        assert prepared is not None
        print_prepared_ast(prepared, context=context, dialect="clickhouse")

        assert context.access_control_restricted_resources == set()

    @parameterized.expand(
        [
            (["insight"], "Results may exclude insights you don't have access to"),
            (["insight", "dashboard"], "Results may exclude dashboards and insights you don't have access to"),
            (
                ["insight", "dashboard", "notebook"],
                "Results may exclude dashboards, insights and notebooks you don't have access to",
            ),
        ]
    )
    def test_build_access_control_warning_message(self, resources, expected_message):
        # "may exclude", not "were excluded": the guard firing doesn't prove any row was actually
        # dropped — the user's blocked objects may not have matched the query.
        from posthog.hogql.printer.access_control import build_access_control_warning

        warning = build_access_control_warning(resources)
        assert warning is not None
        assert warning.type == "access_control"
        assert warning.resources == sorted(resources)
        assert warning.message == expected_message

    def test_build_access_control_warning_empty(self):
        from posthog.hogql.printer.access_control import build_access_control_warning

        assert build_access_control_warning(set()) is None

    def test_child_table_guard_filters_parent_fk_not_own_pk(self):
        # system.dashboard_tiles inherits the "dashboard" scope and sets access_control_id_field="dashboard_id".
        # Denying a dashboard must filter the tile rows on their dashboard_id FK, not the tile's own id -
        # otherwise a denied dashboard's tiles leak (the deny set holds dashboard ids, never tile ids).
        from posthog.hogql.parser import parse_select

        from posthog.constants import AvailableFeature

        from ee.models import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id="dash-99", access_level="none")

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=self.user,
            enable_select_queries=True,
        )
        prepared = prepare_ast_for_printing(
            parse_select("SELECT id FROM system.dashboard_tiles"),
            context=context,
            dialect="clickhouse",
        )
        assert prepared is not None
        sql = print_prepared_ast(prepared, context=context, dialect="clickhouse")

        deny_keys = [k for k in context.values if k.endswith("_sensitive") and isinstance(context.values[k], list)]
        assert len(deny_keys) == 1
        deny_key = deny_keys[0]
        assert context.values[deny_key] == ["dash-99"]
        # The guard targets the parent FK, never the child's own primary key.
        assert f"notIn(toString(system__dashboard_tiles.dashboard_id), %({deny_key})s)" in sql
        assert "notIn(toString(system__dashboard_tiles.id)" not in sql


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
    """
    Per-object access control for warehouse tables.
    Each DataWarehouseTable is an object of the "warehouse_table" resource (with "warehouse_objects"
    as the inheritance parent). Resource-level "none" should resolve identically to per-object "none".
    """

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

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

    def test_object_level_deny_filters_schema_and_cache_key(self):
        self._create_ac(
            resource="warehouse_table",
            resource_id=str(self.denied_table.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user)

        # Schema filtering: the denied table is dropped from the schema, the allowed one stays.
        assert "denied_table" in database._denied_tables
        assert "allowed_table" not in database._denied_tables
        # Cache correctness: the same deny lands in blocked_resource_ids_by_scope, which feeds the
        # query cache key, so a denied user can't be served another user's cached rows.
        assert database.user_access_control is not None
        assert str(self.denied_table.id) in database.user_access_control.blocked_resource_ids_by_scope.get(
            "warehouse_table", set()
        )

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

    def test_bypass_warehouse_access_control_skips_warehouse_acl(self):
        self._create_ac(
            resource="warehouse_table",
            resource_id=str(self.denied_table.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user, bypass_warehouse_access_control=True)

        assert "denied_table" not in database._denied_tables
        assert "allowed_table" not in database._denied_tables

    def test_bypass_warehouse_access_control_skips_warehouse_acl_without_user(self):
        # The classic background-job case: no user, but the caller explicitly opts in.
        database = Database.create_for(team=self.team, user=None, bypass_warehouse_access_control=True)

        assert "denied_table" not in database._denied_tables
        assert "allowed_table" not in database._denied_tables

    def test_to_printed_hogql_bypass_prints_warehouse_table_userless(self):
        # Guards the fail-closed fix: query runners print the response HogQL userless right after the
        # user-scoped execute. Without the bypass, that print fails closed on a warehouse table; the param
        # must reach the database so warehouse-backed insights don't 500 on the print.
        from posthog.hogql.errors import QueryError
        from posthog.hogql.parser import parse_select
        from posthog.hogql.printer import to_printed_hogql

        query = parse_select("SELECT id FROM allowed_table")
        with self.assertRaises(QueryError):
            to_printed_hogql(query, self.team)
        printed = to_printed_hogql(query, self.team, bypass_warehouse_access_control=True)
        assert "allowed_table" in printed

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

        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

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


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestWarehouseAccessControlEndToEnd(BaseTest):
    """End-to-end: execute_hogql_query (the SQL editor path) raises QueryError
    on a denied warehouse table without ever reaching ClickHouse."""

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        self.membership = membership
        credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=self.team)
        self.denied_table = DataWarehouseTable.objects.create(
            name="denied_warehouse_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=credential,
            url_pattern="s3://bucket/denied/*",
            columns={"id": "String"},
        )

    def test_execute_hogql_query_raises_on_denied_warehouse_table(self):
        from posthog.hogql.errors import QueryError
        from posthog.hogql.query import execute_hogql_query

        from ee.models.rbac.access_control import AccessControl

        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(self.denied_table.id),
            access_level="none",
            organization_member=self.membership,
        )

        # The other tests only assert the table lands in _denied_tables. This one verifies that
        # a table in _denied_tables actually makes the real query path error out.
        database = Database.create_for(team=self.team, user=self.user)
        assert "denied_warehouse_table" in database._denied_tables

        with self.assertRaises(QueryError) as cm:
            execute_hogql_query(
                query="SELECT id FROM denied_warehouse_table",
                team=self.team,
                user=self.user,
            )
        assert "don't have access" in str(cm.exception)
        assert "denied_warehouse_table" in str(cm.exception)

    def test_execute_hogql_query_bypass_warehouse_access_control_skips_denial(self):
        """bypass_warehouse_access_control opt-in should let the query past the access control gate
        (downstream may still fail because there's no real S3 data, but the
        gate must not block it)."""
        from posthog.hogql.context import HogQLContext
        from posthog.hogql.errors import QueryError
        from posthog.hogql.query import execute_hogql_query

        from ee.models.rbac.access_control import AccessControl

        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(self.denied_table.id),
            access_level="none",
            organization_member=self.membership,
        )

        context = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, bypass_warehouse_access_control=True
        )
        try:
            execute_hogql_query(
                query="SELECT id FROM denied_warehouse_table",
                team=self.team,
                user=self.user,
                context=context,
            )
        except QueryError as e:
            # Access control deny would say "don't have access"
            assert "don't have access" not in str(e), f"bypass was not honored: {e}"
        except Exception:
            # Downstream errors (missing S3, etc.) are expected and irrelevant
            # to whether ACL was bypassed.
            pass


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestWarehouseViewAccessControl(BaseTest):
    """Per-object access control warehouse views (DataWarehouseSavedQuery)."""

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

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

    def test_object_level_deny_filters_schema_and_cache_key(self):
        self._create_ac(
            resource="warehouse_view",
            resource_id=str(self.denied_view.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user)

        # Schema filtering: the denied view is dropped from the schema, the allowed one stays.
        assert "denied_view" in database._denied_tables
        assert "allowed_view" not in database._denied_tables
        # Cache correctness: the same deny lands in blocked_resource_ids_by_scope, which feeds the
        # query cache key, so a denied user can't be served another user's cached rows.
        assert database.user_access_control is not None
        assert str(self.denied_view.id) in database.user_access_control.blocked_resource_ids_by_scope.get(
            "warehouse_view", set()
        )

    def test_warehouse_objects_resource_none_denies_all_views(self):
        self._create_ac(resource="warehouse_objects", access_level="none")

        database = Database.create_for(team=self.team, user=self.user)

        assert "denied_view" in database._denied_tables
        assert "allowed_view" in database._denied_tables

    def test_no_user_fails_closed_for_warehouse_views(self):
        database = Database.create_for(team=self.team, user=None)

        assert "denied_view" in database._denied_tables
        assert "allowed_view" in database._denied_tables

    def test_bypass_warehouse_access_control_skips_warehouse_view_acl(self):
        self._create_ac(
            resource="warehouse_view",
            resource_id=str(self.denied_view.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user, bypass_warehouse_access_control=True)

        assert "denied_view" not in database._denied_tables
        assert "allowed_view" not in database._denied_tables

    def test_shared_link_user_skips_warehouse_view_acl_but_hides_system_tables(self):
        self._create_ac(
            resource="warehouse_view",
            resource_id=str(self.denied_view.id),
            access_level="none",
            member=self._membership(),
        )
        viewer = SharedLinkUser(SharingConfiguration(team=self.team, enabled=True))

        database = Database.create_for(team=self.team, user=viewer)

        # A shared-link viewer executes without warehouse access control - the deny is skipped.
        assert "denied_view" not in database._denied_tables
        assert "allowed_view" not in database._denied_tables
        # But scoped system tables stay hidden, exactly like a userless build.
        assert "system.dashboards" in database._denied_tables

    def test_shared_link_user_requires_enabled_configuration(self):
        with self.assertRaises(ValueError):
            SharedLinkUser(SharingConfiguration(team=self.team, enabled=False))

    def test_shared_link_cache_key_differs_from_denied_member(self):
        # Resource-level deny: no per-object IDs land in the cache payload, so the restriction
        # lists alone must keep the two principals' cache keys apart.
        self._create_ac(resource="warehouse_objects", access_level="none")
        query = HogQLQuery(query="SELECT id FROM denied_view")
        shared_user = cast(User, SharedLinkUser(SharingConfiguration(team=self.team, enabled=True)))

        shared_key = get_query_runner(query, self.team, user=shared_user).get_cache_key()
        denied_key = get_query_runner(query, self.team, user=self.user).get_cache_key()

        # A shared-link run executes with the warehouse bypass and writes its result to cache;
        # if the keys collided, the denied member would be served that result on a cache hit
        assert shared_key != denied_key

        # Queries touching no access-controlled tables keep sharing one cache entry across
        # principals - the partition must not cost public dashboards their warmed cache results
        events_query = HogQLQuery(query="SELECT count() FROM events")
        assert (
            get_query_runner(events_query, self.team, user=shared_user).get_cache_key()
            == get_query_runner(events_query, self.team, user=self.user).get_cache_key()
        )

    def test_synthetic_principal_skips_warehouse_view_acl(self):
        self._create_ac(
            resource="warehouse_view",
            resource_id=str(self.denied_view.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=SyntheticUser(self.team, "test-token"))

        # Service-token principals bypass warehouse access control by design (see Database.create_for).
        assert "denied_view" not in database._denied_tables
        assert "system.dashboards" in database._denied_tables

    def _materialize(self, view):
        """Attach a same-named backing DataWarehouseTable to a saved query, mirroring materialization."""
        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=self.team)
        backing_table = DataWarehouseTable.objects.create(
            name=view.name,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            team=self.team,
            credential=credential,
            url_pattern=view.url_pattern,
            columns={"id": "String"},
        )
        view.table = backing_table
        view.is_materialized = True
        view.save(update_fields=["table", "is_materialized"])
        return backing_table

    def test_denied_materialized_view_also_blocks_backing_table(self):
        # A materialized view's backing table shares the view's name. Denying the view must not leave
        # the backing table queryable under that name.
        backing_table = self._materialize(self.denied_view)

        self._create_ac(
            resource="warehouse_view",
            resource_id=str(self.denied_view.id),
            access_level="none",
            member=self._membership(),
        )

        database = Database.create_for(team=self.team, user=self.user)

        assert "denied_view" in database._denied_tables
        # The backing table is excluded from the schema build, so the view owns the name and its
        # denial is authoritative - the name must not resolve to the backing table.
        assert not database.has_table("denied_view")
        assert backing_table.name == "denied_view"

        from posthog.hogql.errors import QueryError

        with self.assertRaises(QueryError) as cm:
            database.get_table("denied_view")
        assert "don't have access" in str(cm.exception)
        assert "Unknown" not in str(cm.exception)

    def test_allowed_materialized_view_still_resolves(self):
        # The backing table is excluded, but the view node still exposes the name (and reads the
        # materialized data via hogql_definition), so an allowed materialized view stays queryable.
        self._materialize(self.allowed_view)

        database = Database.create_for(team=self.team, user=self.user)

        assert "allowed_view" not in database._denied_tables
        assert database.has_table("allowed_view")
