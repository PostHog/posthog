from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.test.base import BaseTest
from posthog.hogql.database.test.tables import (
    create_aapl_stock_table_view,
    create_aapl_stock_s3_table,
    create_nested_aapl_stock_view,
    create_aapl_stock_table_self_referencing,
)


class TestSavedQuery(BaseTest):
    maxDiff = None

    def _init_database(self):
        self.database = create_hogql_database(self.team.pk)
        self.database.aapl_stock_view = create_aapl_stock_table_view()
        self.database.aapl_stock = create_aapl_stock_s3_table()
        self.database.aapl_stock_nested_view = create_nested_aapl_stock_view()
        self.database.aapl_stock_self = create_aapl_stock_table_self_referencing()
        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=self.database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _select(self, query: str, dialect: str = "clickhouse") -> str:
        return print_ast(parse_select(query), self.context, dialect=dialect)

    def test_saved_query_table_select(self):
        self._init_database()

        hogql = self._select(query="SELECT * FROM aapl_stock LIMIT 10", dialect="hogql")
        self.assertEqual(
            hogql,
            "SELECT Date, Open, High, Low, Close, Volume, OpenInt FROM aapl_stock LIMIT 10",
        )

        clickhouse = self._select(query="SELECT * FROM aapl_stock_view LIMIT 10", dialect="clickhouse")

        self.assertEqual(
            clickhouse,
            "SELECT aapl_stock_view.Date, aapl_stock_view.Open, aapl_stock_view.High, aapl_stock_view.Low, aapl_stock_view.Close, aapl_stock_view.Volume, aapl_stock_view.OpenInt FROM (SELECT aapl_stock.Date, aapl_stock.Open, aapl_stock.High, aapl_stock.Low, aapl_stock.Close, aapl_stock.Volume, aapl_stock.OpenInt FROM s3Cluster('posthog', %(hogql_val_0_sensitive)s, %(hogql_val_1)s) AS aapl_stock) AS aapl_stock_view LIMIT 10",
        )

    def test_saved_query_with_alias(self):
        self._init_database()

        hogql = self._select(query="SELECT * FROM aapl_stock LIMIT 10", dialect="hogql")
        self.assertEqual(
            hogql,
            "SELECT Date, Open, High, Low, Close, Volume, OpenInt FROM aapl_stock LIMIT 10",
        )

        clickhouse = self._select(
            query="SELECT * FROM aapl_stock_view AS some_alias LIMIT 10",
            dialect="clickhouse",
        )

        self.assertEqual(
            clickhouse,
            "SELECT some_alias.Date, some_alias.Open, some_alias.High, some_alias.Low, some_alias.Close, some_alias.Volume, some_alias.OpenInt FROM (SELECT aapl_stock.Date, aapl_stock.Open, aapl_stock.High, aapl_stock.Low, aapl_stock.Close, aapl_stock.Volume, aapl_stock.OpenInt FROM s3Cluster('posthog', %(hogql_val_0_sensitive)s, %(hogql_val_1)s) AS aapl_stock) AS some_alias LIMIT 10",
        )
