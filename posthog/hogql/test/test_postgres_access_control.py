from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.django_tables import DjangoTable
from posthog.hogql.printer.postgres_access_control import build_access_control_filter, team_id_guard_for_postgres


class TestTeamIdGuardForPostgres(BaseTest):
    def test_creates_team_id_comparison(self):
        context = HogQLContext(team_id=123)
        table_type = ast.TableType(
            table=DjangoTable(
                fields={},
                db_table="posthog_dashboard",
                hogql_name="dashboard",
                resource="dashboard",
            )
        )

        guard = team_id_guard_for_postgres(table_type, context)

        self.assertIsInstance(guard, ast.CompareOperation)
        self.assertEqual(guard.op, ast.CompareOperationOp.Eq)
        self.assertIsInstance(guard.left, ast.Field)
        self.assertEqual(guard.left.chain, ["team_id"])
        self.assertIsInstance(guard.right, ast.Constant)
        self.assertEqual(guard.right.value, 123)


class TestBuildAccessControlFilter(BaseTest):
    def _create_table(self, resource: str, has_created_by: bool = True) -> DjangoTable:
        return DjangoTable(
            fields={},
            db_table=f"posthog_{resource}",
            hogql_name=resource,
            resource=resource,
            has_created_by=has_created_by,
        )

    def test_returns_none_for_org_admin(self):
        context = HogQLContext(
            team_id=1,
            user_id=1,
            is_org_admin=True,
        )
        table = self._create_table("dashboard")
        table_type = ast.TableType(table=table)

        result = build_access_control_filter(table, table_type, context)

        self.assertIsNone(result)

    def test_returns_none_for_non_access_controlled_resource(self):
        context = HogQLContext(
            team_id=1,
            user_id=1,
            is_org_admin=False,
        )
        # Create table with a resource that's not in ACCESS_CONTROL_RESOURCES
        table = DjangoTable(
            fields={},
            db_table="posthog_other",
            hogql_name="other",
            resource=None,
        )
        table_type = ast.TableType(table=table)

        result = build_access_control_filter(table, table_type, context)

        self.assertIsNone(result)

    def test_creates_creator_check_when_has_created_by(self):
        context = HogQLContext(
            team_id=1,
            user_id=42,
            is_org_admin=False,
            organization_membership_id="mem-123",
        )
        table = self._create_table("dashboard", has_created_by=True)
        table_type = ast.TableType(table=table)

        result = build_access_control_filter(table, table_type, context)

        self.assertIsNotNone(result)
        # Should be an Or expression containing creator check
        self.assertIsInstance(result, ast.Or)

    def test_no_filter_when_no_user_context(self):
        context = HogQLContext(
            team_id=1,
            user_id=None,  # No user
            is_org_admin=False,
        )
        table = self._create_table("dashboard")
        table_type = ast.TableType(table=table)

        result = build_access_control_filter(table, table_type, context)

        self.assertIsNone(result)
