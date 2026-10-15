from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.printer.access_control import filter_to_expr

from products.authz.backend.facade.contracts import ResourceIds


class TestHogQLAccessFilter(SimpleTestCase):
    @parameterized.expand([("only", False, "in("), ("except", True, "notin(")])
    def test_filter_uses_the_resource_id_and_null_safe_creator(self, _name: str, excluded: bool, operator: str) -> None:
        table = SystemTables().children["dashboards"].table
        assert isinstance(table, Table)
        table_type = ast.TableType(table=table)
        result = ResourceIds(ids=frozenset({"1"}), complete=True, excluded=excluded, creator_exempt=True)
        guard = filter_to_expr(result, "id", table_type, "created_by_id", 7)
        assert guard is not None
        sql = print_prepared_ast(guard, HogQLContext(team_id=1), dialect="hogql").lower()
        assert operator in sql
        assert "tostring(id)" in sql
        assert "ifnull" in sql and "created_by_id" in sql and "7" in sql

    def test_unrestricted_and_capped_results(self) -> None:
        table = SystemTables().children["dashboards"].table
        assert isinstance(table, Table)
        table_type = ast.TableType(table=table)
        assert (
            filter_to_expr(ResourceIds(ids=frozenset(), complete=True, excluded=True), "id", table_type, None, 1)
            is None
        )
        guard = filter_to_expr(
            ResourceIds(ids=frozenset(), complete=False, creator_exempt=True), "id", table_type, "created_by_id", 1
        )
        assert isinstance(guard, ast.Constant) and guard.value is False
