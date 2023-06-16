from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.test.base import BaseTest
from posthog.hogql.database.test.tables import create_aapl_stock_s3_table


class TestS3Table(BaseTest):
    def _init_database(self):
        self.database = create_hogql_database(self.team.pk)
        self.database.aapl_stock = create_aapl_stock_s3_table()
        self.context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=self.database)

    def _select(self, query: str, dialect: str = "clickhouse") -> str:
        return print_ast(parse_select(query), self.context, dialect=dialect)

    def test_s3_table_select(self):
        self._init_database()

        hogql = self._select(query="SELECT * FROM aapl_stock LIMIT 10", dialect="hogql")
        self.assertEqual(hogql, "SELECT Date, Open, High, Low, Close, Volume, OpenInt FROM aapl_stock LIMIT 10")

        clickhouse = self._select(query="SELECT * FROM aapl_stock LIMIT 10", dialect="clickhouse")
        self.assertEqual(
            clickhouse,
            "SELECT aapl_stock.Date, aapl_stock.Open, aapl_stock.High, aapl_stock.Low, aapl_stock.Close, aapl_stock.Volume, aapl_stock.OpenInt FROM s3(%(hogql_val_0)s, %(hogql_val_1)s) AS aapl_stock LIMIT 10",
        )

    def test_s3_table_select_with_alias(self):
        self._init_database()

        hogql = self._select(query="SELECT High, Low FROM aapl_stock AS a LIMIT 10", dialect="hogql")
        self.assertEqual(hogql, "SELECT High, Low FROM aapl_stock AS a LIMIT 10")

        clickhouse = self._select(query="SELECT High, Low FROM aapl_stock AS a LIMIT 10", dialect="clickhouse")
        self.assertEqual(
            clickhouse,
            "SELECT a.High, a.Low FROM s3(%(hogql_val_0)s, %(hogql_val_1)s) AS a LIMIT 10",
        )
