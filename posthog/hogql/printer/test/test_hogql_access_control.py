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


class TestObjectLevelAccessControl(BaseTest):
    """Object-level access control: the printer should inject a subquery-based
    deny/allow filter against the internal `_posthog_internal_access_control`
    table.
    """

    def _enable_ac(self):
        from posthog.constants import AvailableFeature

        # `ROLE_BASED_ACCESS` is required for `UserAccessControl._user_role_ids`
        # to load — without it role-based ACL rows are silently ignored.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()
        return membership

    def _compile_select(self, query: str, context: HogQLContext) -> str:
        from posthog.hogql.parser import parse_select

        node = parse_select(query)
        prepared = prepare_ast_for_printing(node, context=context, dialect="clickhouse")
        assert prepared is not None
        return print_prepared_ast(prepared, context=context, dialect="clickhouse")

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_deny_list_predicate_is_injected_for_member_with_resource_access(self):
        from ee.models import AccessControl

        membership = self._enable_ac()
        # Resource-level default access stays at "editor"; deny a specific dashboard.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
            organization_member=membership,
        )

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )

        sql = self._compile_select("SELECT id FROM system.dashboards", ctx)

        assert "notIn" in sql, "deny-list path should emit NOT IN"
        assert "countIf" in sql, "deny-list path should include the countIf precedence logic"
        # The internal table is referenced inside the subquery, but resolved by
        # alias — its postgres table name (`ee_accesscontrol`) goes into the
        # sensitive values dict, not into the rendered SQL text.
        assert "ee_accesscontrol" not in sql
        # And the resource_id we denied is *not* in the SQL text either.
        assert "'42'" not in sql

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_allow_list_predicate_for_resource_none_plus_specific_grant(self):
        from ee.models import AccessControl

        membership = self._enable_ac()
        # Resource-level "none" (project-wide default).
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            access_level="none",
        )
        # But the user gets an explicit allow on one dashboard.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="viewer",
            organization_member=membership,
        )

        database = Database.create_for(team=self.team, user=self.user)
        # The table must remain in the schema: user has specific access.
        system_node = database.tables.children.get("system")
        assert system_node is not None
        assert "dashboards" in system_node.children, (
            "system.dashboards should remain queryable when the user has specific allow grants"
        )

        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )
        sql = self._compile_select("SELECT id FROM system.dashboards", ctx)

        # Allow-list branch: IN, not NOT IN.
        assert "notIn(toString(system__dashboards.id)" not in sql
        assert "in(toString(system__dashboards.id)" in sql

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_creator_bypass_emitted_for_table_with_created_by_id(self):
        """Tables that expose `created_by_id` get an OR-clause exempting the
        user's own rows from the deny list — matches the
        `Q(created_by=self._user)` OR in `filter_queryset_by_access_level`.

        We use `system.insights` because it exposes `created_by_id`;
        `system.dashboards` deliberately does not.
        """
        from ee.models import AccessControl

        membership = self._enable_ac()
        AccessControl.objects.create(
            team=self.team,
            resource="insight",
            resource_id="1",
            access_level="none",
            organization_member=membership,
        )

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )
        sql = self._compile_select("SELECT id FROM system.insights", ctx)

        # The predicate is wrapped in `or(<deny subquery>, equals(created_by_id, <user_id>))`.
        assert "notIn" in sql, "deny-list path should emit NOT IN"
        assert f"system__insights.created_by_id" in sql, "creator bypass missing — created_by_id reference"

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_creator_bypass_absent_for_table_without_created_by_id(self):
        """`system.dashboards` does not expose `created_by_id`, so the bypass
        clause must NOT be emitted (the predicate would otherwise fail to
        resolve)."""
        from ee.models import AccessControl

        membership = self._enable_ac()
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="1",
            access_level="none",
            organization_member=membership,
        )

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )
        sql = self._compile_select("SELECT id FROM system.dashboards", ctx)

        assert "notIn" in sql
        assert "created_by_id" not in sql, "should not reference created_by_id on a table that doesn't expose it"

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_admin_skips_object_level_predicate(self):
        from ee.models import AccessControl

        self._enable_ac()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
        )

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )
        sql = self._compile_select("SELECT id FROM system.dashboards", ctx)

        # Admin bypasses the entire object-level filter.
        assert "notIn" not in sql
        assert "countIf" not in sql

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_no_predicate_when_no_acl_rows_for_resource(self):
        """Cheap short-circuit: if the team has no `ee_accesscontrol` rows for
        this resource at all, no subquery is emitted."""
        self._enable_ac()

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )
        sql = self._compile_select("SELECT id FROM system.dashboards", ctx)

        assert "notIn" not in sql
        assert "countIf" not in sql

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_predicate_fires_when_only_object_level_rows_exist(self):
        """Regression: the short-circuit must NOT use
        `has_access_levels_for_resource` (which only counts resource-level
        rows with `resource_id IS NULL`). A user with only object-level ACL
        grants previously fell through with no predicate attached, silently
        leaking the denied rows.
        """
        from ee.models import AccessControl

        membership = self._enable_ac()
        # Object-level row only — no resource-level (`resource_id IS NULL`) row.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="7",
            access_level="none",
            organization_member=membership,
        )

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )
        sql = self._compile_select("SELECT id FROM system.dashboards", ctx)

        assert "notIn" in sql, "predicate must fire when only object-level ACL rows exist"
        assert "countIf" in sql

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_internal_table_is_not_user_queryable(self):
        from posthog.hogql.database.schema.access_control_internal import INTERNAL_ACCESS_CONTROL_TABLE_NAME
        from posthog.hogql.errors import QueryError

        from ee.models import AccessControl

        self._enable_ac()
        # Force a predicate to be built so the internal table gets registered.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
        )

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )

        # The internal table IS in the tree (predicate needs it)…
        assert INTERNAL_ACCESS_CONTROL_TABLE_NAME in database._internal_table_names
        # …but direct user queries are rejected.
        with self.assertRaises(QueryError) as cm:
            self._compile_select(f"SELECT * FROM {INTERNAL_ACCESS_CONTROL_TABLE_NAME}", ctx)
        assert "Unknown table" in str(cm.exception)

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_internal_table_excluded_from_autocomplete(self):
        from posthog.hogql.database.schema.access_control_internal import INTERNAL_ACCESS_CONTROL_TABLE_NAME

        from ee.models import AccessControl

        self._enable_ac()
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
        )

        database = Database.create_for(team=self.team, user=self.user)

        # The autocomplete / data-management surfaces must not list the internal name.
        assert INTERNAL_ACCESS_CONTROL_TABLE_NAME not in database.get_posthog_table_names()
        assert INTERNAL_ACCESS_CONTROL_TABLE_NAME not in database.get_posthog_table_names(include_hidden=True)
        assert INTERNAL_ACCESS_CONTROL_TABLE_NAME not in database.get_system_table_names()
        assert INTERNAL_ACCESS_CONTROL_TABLE_NAME not in database.get_all_table_names()

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_deny_includes_default_row(self):
        """A default ACL row (member IS NULL AND role IS NULL) with
        access_level='none' on a specific resource_id must be honored — the
        defaults-only branch of the HAVING clause is what catches it.
        """
        from ee.models import AccessControl

        self._enable_ac()
        # Default "none" on dashboard 7, no member or role attached.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="7",
            access_level="none",
        )

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )
        sql = self._compile_select("SELECT id FROM system.dashboards", ctx)

        assert "notIn" in sql, "deny-list should fire for default 'none' on a resource_id"
        # Both the explicit-branch and defaults-branch of the HAVING clause
        # need to be present; the latter is what catches the default row.
        assert "countIf" in sql

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_deny_includes_role_match(self):
        """When the user is in a role and an ACL denies that role on a
        specific resource_id, the predicate must include the role in the
        user-relevance filter (`role_id IN tuple(...)`)."""
        from ee.models import AccessControl
        from ee.models.rbac.role import Role, RoleMembership

        membership = self._enable_ac()
        role = Role.objects.create(name="smoke-role", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=membership)

        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="5",
            access_level="none",
            role=role,
        )

        database = Database.create_for(team=self.team, user=self.user)
        ctx = HogQLContext(
            team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
        )
        sql = self._compile_select("SELECT id FROM system.dashboards", ctx)

        assert "notIn" in sql
        # The role_id IN tuple(...) clause is rendered as `in(...role_id, tuple(...))`.
        assert "role_id" in sql
        assert "tuple(" in sql, "role_ids tuple missing from subquery"

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_parity_with_filter_queryset_by_access_level(self):
        """The HogQL predicate must filter the same resource_ids as the Python
        `filter_queryset_by_access_level` queryset filter would.

        We can't execute the rendered ClickHouse SQL in this test (the printer
        emits `postgresql(...)` table-function calls that only ClickHouse can
        run). Instead we re-derive what the predicate's inner subquery
        *would* return — the blocked or allowed `resource_id` set — using the
        same access-control rows it would query, and compare that set to the
        IDs `filter_queryset_by_access_level` actually excludes (or restricts
        to).
        """
        from posthog.models.dashboard import Dashboard
        from posthog.rbac.user_access_control import NO_ACCESS_LEVEL, UserAccessControl

        from ee.models import AccessControl
        from ee.models.rbac.role import Role, RoleMembership

        membership = self._enable_ac()
        role = Role.objects.create(name="parity-role", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=membership)

        # Build a corpus of dashboards in this team — Dashboard IDs are
        # autoincremented and global, so we cannot hard-code them.
        d_member_denied = Dashboard.objects.create(team=self.team, name="member-denied")
        d_role_denied = Dashboard.objects.create(team=self.team, name="role-denied")
        d_default_denied = Dashboard.objects.create(team=self.team, name="default-denied")
        d_member_allowed_via_explicit = Dashboard.objects.create(team=self.team, name="member-allow-explicit")
        d_unfiltered = Dashboard.objects.create(team=self.team, name="unfiltered")

        # Member-specific deny on one dashboard.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(d_member_denied.id),
            access_level="none",
            organization_member=membership,
        )
        # Role-specific deny on another.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(d_role_denied.id),
            access_level="none",
            role=role,
        )
        # Default deny on a third (no member, no role).
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(d_default_denied.id),
            access_level="none",
        )
        # Default deny plus explicit allow for this member — should NOT block.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(d_member_allowed_via_explicit.id),
            access_level="none",
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(d_member_allowed_via_explicit.id),
            access_level="editor",
            organization_member=membership,
        )

        uac = UserAccessControl(user=self.user, team=self.team)
        # Sanity: this user has resource-level access (default editor).
        assert uac.access_level_for_resource("dashboard") != NO_ACCESS_LEVEL

        # 1) Reference set — IDs the Python filter retains.
        queryset = Dashboard.objects.filter(team=self.team)
        queryset_allowed_ids = set(uac.filter_queryset_by_access_level(queryset).values_list("id", flat=True))

        # 2) Re-derive the SAME set using only the data the printer's subquery
        # would see — the cached access controls. Mirrors the HAVING logic.
        filters = uac.access_controls_filters_for_queryset("dashboard")
        rows = uac.get_access_controls(filters)
        by_resource_id: dict[str, list] = {}
        for ac in rows:
            by_resource_id.setdefault(ac.resource_id, []).append(ac)

        blocked: set[str] = set()
        for resource_id, group in by_resource_id.items():
            explicit = [ac for ac in group if ac.organization_member is not None or ac.role is not None]
            if explicit:
                if all(ac.access_level == NO_ACCESS_LEVEL for ac in explicit):
                    blocked.add(resource_id)
            else:
                # Defaults only.
                if all(ac.access_level == NO_ACCESS_LEVEL for ac in group):
                    blocked.add(resource_id)

        # The Python filter also bypasses for the creator, but for Dashboard
        # we set `created_by` to None implicitly, so no bypass applies.
        all_ids = set(Dashboard.objects.filter(team=self.team).values_list("id", flat=True))
        predicate_allowed_ids = all_ids - {int(rid) for rid in blocked if rid.isdigit()}

        assert queryset_allowed_ids == predicate_allowed_ids, (
            f"queryset filter and predicate diverge:\n"
            f"  queryset: {sorted(queryset_allowed_ids)}\n"
            f"  predicate: {sorted(predicate_allowed_ids)}\n"
            f"  blocked-by-predicate: {sorted(blocked)}\n"
            f"  rows: {[(ac.resource_id, ac.access_level, ac.organization_member_id, ac.role_id) for ac in rows]}"
        )

        # Also assert this excludes exactly the dashboards we expect.
        assert d_member_denied.id not in queryset_allowed_ids
        assert d_role_denied.id not in queryset_allowed_ids
        assert d_default_denied.id not in queryset_allowed_ids
        assert d_member_allowed_via_explicit.id in queryset_allowed_ids
        assert d_unfiltered.id in queryset_allowed_ids

    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_predicate_does_not_pollute_shared_module_singletons(self):
        """Two Database.create_for calls for two users with different ACL configurations
        must not see each other's predicates on the shared schema singletons."""
        from posthog.hogql.database.schema.system import SystemTables

        from ee.models import AccessControl

        self._enable_ac()
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
        )

        # Build a database with the predicate attached…
        db_for_user = Database.create_for(team=self.team, user=self.user)

        # …and a freshly-created SystemTables singleton — its dashboards table
        # must still have no predicates attached.
        fresh = SystemTables()
        fresh_dashboards = fresh.children["dashboards"].table
        # `.predicates` is `[]` by default; an empty list is fine.
        assert getattr(fresh_dashboards, "predicates", []) == [], (
            "Module-level SystemTables instance was mutated by Database.create_for — predicates leaked across users"
        )

        # And the per-Database copy DOES carry the predicate.
        system_node = db_for_user.tables.children.get("system")
        assert system_node is not None
        dashboards_node = system_node.children.get("dashboards")
        assert dashboards_node is not None
        assert len(dashboards_node.table.predicates) >= 1, "Per-Database copy is missing the object-level predicate"
