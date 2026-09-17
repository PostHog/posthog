from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_ast_for_printing, print_prepared_ast

from posthog.query_scan.stub import stub_in_subqueries

from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable


class TestStubPrintsAsClickHouse(BaseTest):
    def test_the_stubbed_tree_and_its_subqueries_print_in_the_clickhouse_dialect(self) -> None:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        prepared = prepare_ast_for_printing(
            node=parse_select(
                "SELECT count() FROM events "
                "WHERE distinct_id IN (SELECT distinct_id FROM events WHERE event = 'x') "
                "AND timestamp >= (SELECT min(timestamp) FROM events)"
            ),
            context=context,
            dialect="clickhouse",
        )

        assert prepared is not None
        stub = stub_in_subqueries(prepared)
        sql = print_prepared_ast(stub.stubbed, context, dialect="clickhouse")
        subquery_sql = print_prepared_ast(stub_in_subqueries(stub.subqueries[0]).stubbed, context, dialect="clickhouse")

        assert "(SELECT" not in sql.replace("\n", " ")
        assert len(stub.subqueries) == 2
        assert "events" in subquery_sql and "IN (SELECT" not in subquery_sql

    def test_a_warehouse_table_prints_as_an_empty_table_without_its_credentials(self) -> None:
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        DataWarehouseTable.objects.create(
            team=self.team,
            name="customers",
            format="Parquet",
            url_pattern="http://localhost/customers/*.parquet",
            credential=credential,
            columns={"id": "String", "plan": "String"},
        )
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        prepared = prepare_ast_for_printing(
            node=parse_select("SELECT count() FROM events AS e JOIN customers AS c ON e.distinct_id = c.id"),
            context=context,
            dialect="clickhouse",
        )
        assert prepared is not None

        sql = print_prepared_ast(stub_in_subqueries(prepared).stubbed, context, dialect="clickhouse")

        assert "null(" in sql and "s3(" not in sql
        assert "`id` String, `plan` String" in context.values.values()
        assert not any(key.endswith("_sensitive") for key in context.values)
