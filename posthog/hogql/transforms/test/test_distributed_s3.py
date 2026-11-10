import pytest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringDatabaseField, Table
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.distributed_s3 import can_distribute_warehouse_query
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import Team

from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class _BindSources(TraversingVisitor):
    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            name = str(node.table.chain[0])
            table = (
                HogQLDataWarehouseTable(
                    name=name,
                    url="https://bucket.example.com/orders",
                    format="DeltaS3Wrapper",
                    table_id=name,
                    fields={"id": StringDatabaseField(name="id")},
                )
                if name.startswith("warehouse_")
                else Table(name=name, fields={"id": StringDatabaseField(name="id")})
            )
            node.table.type = ast.TableType(table=table)
        super().visit_join_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        pass


@pytest.mark.parametrize("enabled,reader", [(False, "s3("), (True, "s3Cluster(")])
def test_source_reader_is_opt_in(enabled: bool, reader: str) -> None:
    table = DataWarehouseTable(
        name="warehouse_orders",
        team=Team(id=1),
        format="DeltaS3Wrapper",
        url_pattern="https://bucket.example.com/orders",
        queryable_folder="orders__query_c",
        size_in_s3_mib=4096.0,
    )
    context = HogQLContext(team_id=1)
    context.allow_s3_cluster = enabled

    assert table.hogql_definition().to_printed_clickhouse(context).startswith(reader)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("SELECT id FROM warehouse_orders", True),
        ("SELECT count() FROM warehouse_orders AS orders GROUP BY id", True),
        ("SELECT id FROM warehouse_orders UNION ALL SELECT id FROM warehouse_customers", True),
        ("SELECT id FROM (SELECT id FROM warehouse_orders)", True),
        ("SELECT 1", False),
        ("SELECT event FROM events", False),
        ("SELECT id FROM warehouse_orders JOIN warehouse_customers USING id", False),
        ("SELECT event FROM events WHERE event IN (SELECT id FROM warehouse_orders)", False),
        ("SELECT id FROM warehouse_orders WHERE id IN (SELECT id FROM warehouse_customers)", False),
        ("SELECT (SELECT max(id) FROM warehouse_customers) FROM warehouse_orders", False),
        ("SELECT (SELECT 1) FROM warehouse_orders", False),
        ("WITH orders AS (SELECT id FROM warehouse_orders) SELECT id FROM orders", False),
        ("SELECT id FROM warehouse_orders UNION DISTINCT SELECT id FROM warehouse_customers", False),
        ("SELECT number FROM numbers(2)", False),
    ],
)
def test_only_standalone_warehouse_scans_can_distribute(query: str, expected: bool) -> None:
    node = parse_select(query)
    _BindSources().visit(node)

    assert can_distribute_warehouse_query(node) is expected


def test_unresolved_sources_do_not_distribute() -> None:
    assert not can_distribute_warehouse_query(parse_select("SELECT id FROM warehouse_orders"))
