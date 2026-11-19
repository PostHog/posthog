import pytest

from posthog.hogql import ast
from posthog.hogql.database.models import IntegerDatabaseField, Table
from posthog.hogql.database.s3_table import DataWarehouseTable
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.distributed_s3 import can_distribute_warehouse_query
from posthog.hogql.visitor import TraversingVisitor


class _BindSources(TraversingVisitor):
    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            name = str(node.table.chain[0])
            table = (
                DataWarehouseTable(
                    name=name,
                    url="https://bucket.example.com/source/*.parquet",
                    format="Parquet",
                    table_id=name,
                    fields={"value": IntegerDatabaseField(name="value")},
                )
                if name.startswith("warehouse_")
                else Table(name=name, fields={"value": IntegerDatabaseField(name="value")})
            )
            node.table.type = ast.TableType(table=table)
        super().visit_join_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        pass


@pytest.mark.parametrize(
    "query,expected",
    [
        ("SELECT value FROM warehouse_source", True),
        ("SELECT count() FROM warehouse_source AS src GROUP BY value", True),
        ("SELECT value FROM warehouse_source UNION ALL SELECT value FROM warehouse_other", True),
        ("SELECT value FROM (SELECT value FROM warehouse_source)", True),
        ("SELECT 1", False),
        ("SELECT value FROM events", False),
        ("SELECT value FROM warehouse_source JOIN warehouse_other USING value", False),
        ("SELECT value FROM events WHERE value IN (SELECT value FROM warehouse_source)", False),
        ("SELECT value FROM warehouse_source WHERE value IN (SELECT value FROM warehouse_other)", False),
        ("SELECT (SELECT max(value) FROM warehouse_other) FROM warehouse_source", False),
        ("SELECT (SELECT 1) FROM warehouse_source", False),
        ("WITH src AS (SELECT value FROM warehouse_source) SELECT value FROM src", False),
        ("SELECT value FROM warehouse_source UNION DISTINCT SELECT value FROM warehouse_other", False),
        ("SELECT number FROM numbers(2)", False),
    ],
)
def test_only_standalone_warehouse_scans_can_distribute(query: str, expected: bool) -> None:
    node = parse_select(query)
    _BindSources().visit(node)

    assert can_distribute_warehouse_query(node) is expected


def test_unresolved_sources_do_not_distribute() -> None:
    assert not can_distribute_warehouse_query(parse_select("SELECT value FROM warehouse_source"))
