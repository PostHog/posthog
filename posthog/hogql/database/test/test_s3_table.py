from typing import Literal
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.database.s3_table import build_function_call
from posthog.hogql.database.test.tables import create_aapl_stock_s3_table
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.test.base import BaseTest
from posthog.warehouse.models.table import DataWarehouseTable


class TestS3Table(BaseTest):
    def _init_database(self):
        self.database = create_hogql_database(team=self.team)
        self.database.add_warehouse_tables(
            aapl_stock=create_aapl_stock_s3_table(), aapl_stock_2=create_aapl_stock_s3_table(name="aapl_stock_2")
        )
        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=self.database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _select(self, query: str, dialect: Literal["hogql", "clickhouse"] = "clickhouse") -> str:
        return print_ast(parse_select(query), self.context, dialect=dialect)

    def test_s3_table_select(self):
        self._init_database()

        hogql = self._select(query="SELECT * FROM aapl_stock LIMIT 10", dialect="hogql")
        self.assertEqual(
            hogql,
            "SELECT Date, Open, High, Low, Close, Volume, OpenInt FROM aapl_stock LIMIT 10",
        )

        clickhouse = self._select(query="SELECT * FROM aapl_stock LIMIT 10", dialect="clickhouse")

        self.assertEqual(
            clickhouse,
            "SELECT aapl_stock.Date AS Date, aapl_stock.Open AS Open, aapl_stock.High AS High, aapl_stock.Low AS Low, aapl_stock.Close AS Close, aapl_stock.Volume AS Volume, aapl_stock.OpenInt AS OpenInt FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s) AS aapl_stock LIMIT 10",
        )

    def test_s3_table_select_with_alias(self):
        self._init_database()

        hogql = self._select(query="SELECT High, Low FROM aapl_stock AS a LIMIT 10", dialect="hogql")
        self.assertEqual(hogql, "SELECT High, Low FROM aapl_stock AS a LIMIT 10")

        clickhouse = self._select(query="SELECT High, Low FROM aapl_stock AS a LIMIT 10", dialect="clickhouse")

        # Alias will completely override table name to prevent ambiguous table names that can be shared if the same table is joinedfrom multiple times
        self.assertEqual(
            clickhouse,
            "SELECT a.High AS High, a.Low AS Low FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s) AS a LIMIT 10",
        )

    def test_s3_table_select_join(self):
        self._init_database()

        hogql = self._select(
            query="SELECT aapl_stock.High, aapl_stock.Low FROM aapl_stock JOIN aapl_stock_2 ON aapl_stock.High = aapl_stock_2.High LIMIT 10",
            dialect="hogql",
        )
        self.assertEqual(
            hogql,
            "SELECT aapl_stock.High, aapl_stock.Low FROM aapl_stock JOIN aapl_stock_2 ON equals(aapl_stock.High, aapl_stock_2.High) LIMIT 10",
        )

        clickhouse = self._select(
            query="SELECT aapl_stock.High, aapl_stock.Low FROM aapl_stock JOIN aapl_stock_2 ON aapl_stock.High = aapl_stock_2.High LIMIT 10",
            dialect="clickhouse",
        )

        self.assertEqual(
            clickhouse,
            "SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM (SELECT * FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s)) AS aapl_stock JOIN (SELECT * FROM s3(%(hogql_val_2_sensitive)s, %(hogql_val_3)s)) AS aapl_stock_2 ON equals(aapl_stock.High, aapl_stock_2.High) LIMIT 10",
        )

    def test_s3_table_select_join_with_alias(self):
        self._init_database()

        hogql = self._select(
            query="SELECT a.High, a.Low FROM aapl_stock AS a JOIN aapl_stock AS b ON a.High = b.High LIMIT 10",
            dialect="hogql",
        )
        self.assertEqual(
            hogql,
            "SELECT a.High, a.Low FROM aapl_stock AS a JOIN aapl_stock AS b ON equals(a.High, b.High) LIMIT 10",
        )

        clickhouse = self._select(
            query="SELECT a.High, a.Low FROM aapl_stock AS a JOIN aapl_stock AS b ON a.High = b.High LIMIT 10",
            dialect="clickhouse",
        )

        # Alias will completely override table name to prevent ambiguous table names that can be shared if the same table is joinedfrom multiple times
        self.assertEqual(
            clickhouse,
            "SELECT a.High AS High, a.Low AS Low FROM (SELECT * FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s)) AS a JOIN (SELECT * FROM s3(%(hogql_val_2_sensitive)s, %(hogql_val_3)s)) AS b ON equals(a.High, b.High) LIMIT 10",
        )

    def test_s3_table_select_and_non_s3_join(self):
        self._init_database()

        hogql = self._select(
            query="SELECT aapl_stock.High, aapl_stock.Low FROM aapl_stock JOIN events ON aapl_stock.High = events.event LIMIT 10",
            dialect="hogql",
        )
        self.assertEqual(
            hogql,
            "SELECT aapl_stock.High, aapl_stock.Low FROM aapl_stock JOIN events ON equals(aapl_stock.High, events.event) LIMIT 10",
        )

        clickhouse = self._select(
            query="SELECT aapl_stock.High, aapl_stock.Low FROM aapl_stock JOIN events ON aapl_stock.High = events.event LIMIT 10",
            dialect="clickhouse",
        )

        self.assertEqual(
            clickhouse,
            f"SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM (SELECT * FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s)) AS aapl_stock JOIN events ON equals(aapl_stock.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
        )

    def test_s3_table_select_and_non_s3_join_first(self):
        self._init_database()

        hogql = self._select(
            query="SELECT aapl_stock.High, aapl_stock.Low FROM aapl_stock JOIN events ON aapl_stock.High = events.event LIMIT 10",
            dialect="hogql",
        )
        self.assertEqual(
            hogql,
            "SELECT aapl_stock.High, aapl_stock.Low FROM aapl_stock JOIN events ON equals(aapl_stock.High, events.event) LIMIT 10",
        )

        clickhouse = self._select(
            query="SELECT aapl_stock.High, aapl_stock.Low FROM events JOIN aapl_stock ON aapl_stock.High = events.event LIMIT 10",
            dialect="clickhouse",
        )

        self.assertEqual(
            clickhouse,
            f"SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM events GLOBAL JOIN (SELECT * FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s)) AS aapl_stock ON equals(aapl_stock.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
        )

        clickhouse = self._select(
            query="SELECT aapl_stock.High, aapl_stock.Low FROM events LEFT JOIN aapl_stock ON aapl_stock.High = events.event LIMIT 10",
            dialect="clickhouse",
        )

        self.assertEqual(
            clickhouse,
            f"SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM events GLOBAL LEFT JOIN (SELECT * FROM s3(%(hogql_val_2_sensitive)s, %(hogql_val_3)s)) AS aapl_stock ON equals(aapl_stock.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
        )

        clickhouse = self._select(
            query="SELECT aapl_stock.High, aapl_stock.Low FROM events RIGHT JOIN aapl_stock ON aapl_stock.High = events.event LIMIT 10",
            dialect="clickhouse",
        )

        self.assertEqual(
            clickhouse,
            f"SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM events GLOBAL RIGHT JOIN (SELECT * FROM s3(%(hogql_val_4_sensitive)s, %(hogql_val_5)s)) AS aapl_stock ON equals(aapl_stock.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
        )

    def test_s3_table_select_alias_escaped(self):
        self._init_database()

        escaped_table = create_aapl_stock_s3_table(name="random as (SELECT * FROM events), SELECT * FROM events --")
        self.database.add_warehouse_tables(
            **{"random as (SELECT * FROM events), SELECT * FROM events --": escaped_table}
        )

        hogql = self._select(
            query='SELECT High, Low FROM "random as (SELECT * FROM events), SELECT * FROM events --" JOIN events ON "random as (SELECT * FROM events), SELECT * FROM events --".High = events.event LIMIT 10',
            dialect="hogql",
        )
        self.assertEqual(
            hogql,
            "SELECT High, Low FROM `random as (SELECT * FROM events), SELECT * FROM events --` AS `random as (SELECT * FROM events), SELECT * FROM events --` JOIN events ON equals(`random as (SELECT * FROM events), SELECT * FROM events --`.High, events.event) LIMIT 10",
        )

        clickhouse = self._select(
            query='SELECT High, Low FROM "random as (SELECT * FROM events), SELECT * FROM events --" JOIN events ON "random as (SELECT * FROM events), SELECT * FROM events --".High = events.event LIMIT 10',
            dialect="clickhouse",
        )

        # table name is escaped
        self.assertEqual(
            clickhouse,
            f"SELECT `random as (SELECT * FROM events), SELECT * FROM events --`.High AS High, `random as (SELECT * FROM events), SELECT * FROM events --`.Low AS Low FROM (SELECT * FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s)) AS `random as (SELECT * FROM events), SELECT * FROM events --` JOIN events ON equals(`random as (SELECT * FROM events), SELECT * FROM events --`.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
        )

    def test_s3_table_select_table_name_bad_character(self):
        self._init_database()

        escaped_table = create_aapl_stock_s3_table(name="some%(asd)sname")
        self.database.add_warehouse_tables(**{"some%(asd)sname": escaped_table})

        with self.assertRaises(ExposedHogQLError) as context:
            self._select(query='SELECT * FROM "some%(asd)sname" LIMIT 10', dialect="clickhouse")
            self.assertTrue("Alias \"some%(asd)sname\" contains unsupported character '%'" in str(context.exception))

    def test_s3_table_select_in(self):
        self._init_database()

        hogql = self._select(
            query="SELECT uuid, event FROM events WHERE event IN (SELECT Date FROM aapl_stock)",
            dialect="hogql",
        )
        self.assertEqual(
            hogql,
            f"SELECT uuid, event FROM events WHERE globalIn(event, (SELECT Date FROM aapl_stock)) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        clickhouse = self._select(
            query="SELECT uuid, event FROM events WHERE event IN (SELECT Date FROM aapl_stock)",
            dialect="clickhouse",
        )

        self.assertEqual(
            clickhouse,
            f"SELECT events.uuid AS uuid, events.event AS event FROM events WHERE and(equals(events.team_id, {self.team.pk}), ifNull(globalIn(events.event, (SELECT aapl_stock.Date AS Date FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s) AS aapl_stock)), 0)) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_s3_build_function_call_without_context(self):
        res = build_function_call("http://url.com", DataWarehouseTable.TableFormat.Parquet, "key", "secret", None, None)
        assert res == "s3('http://url.com', 'key', 'secret', 'Parquet')"

    def test_s3_build_function_call_without_context_with_structure(self):
        res = build_function_call(
            "http://url.com", DataWarehouseTable.TableFormat.Parquet, "key", "secret", "some structure", None
        )
        assert res == "s3('http://url.com', 'key', 'secret', 'Parquet', 'some structure')"

    def test_s3_build_function_call_without_context_and_delta_format(self):
        res = build_function_call("http://url.com", DataWarehouseTable.TableFormat.Delta, "key", "secret", None, None)
        assert res == "deltaLake('http://url.com', 'key', 'secret')"

    def test_s3_build_function_call_without_context_and_deltaS3Wrapper_format(self):
        res = build_function_call(
            "http://url.com/folder", DataWarehouseTable.TableFormat.DeltaS3Wrapper, "key", "secret", None, None
        )
        assert res == "s3('http://url.com/folder__query/**.parquet', 'key', 'secret', 'Parquet')"

    def test_s3_build_function_call_without_context_and_deltaS3Wrapper_format_with_slash(self):
        res = build_function_call(
            "http://url.com/folder/", DataWarehouseTable.TableFormat.DeltaS3Wrapper, "key", "secret", None, None
        )
        assert res == "s3('http://url.com/folder__query/**.parquet', 'key', 'secret', 'Parquet')"

    def test_s3_build_function_call_without_context_and_deltaS3Wrapper_format_with_structure(self):
        res = build_function_call(
            "http://url.com/folder",
            DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            "key",
            "secret",
            "some structure",
            None,
        )
        assert res == "s3('http://url.com/folder__query/**.parquet', 'key', 'secret', 'Parquet', 'some structure')"

    def test_s3_build_function_call_without_context_and_delta_format_and_with_structure(self):
        res = build_function_call(
            "http://url.com", DataWarehouseTable.TableFormat.Delta, "key", "secret", "some structure", None
        )
        assert res == "deltaLake('http://url.com', 'key', 'secret', 'some structure')"

    def test_s3_build_function_call_azure(self):
        res = build_function_call(
            "https://tomposthogtest.blob.core.windows.net/somecontainer/path/to/file.parquet",
            DataWarehouseTable.TableFormat.Parquet,
            "tomposthogtest",
            "blah",
            "some structure",
            None,
        )

        assert (
            res
            == "azureBlobStorage('https://tomposthogtest.blob.core.windows.net', 'somecontainer', 'path/to/file.parquet', 'tomposthogtest', 'blah', 'Parquet', 'auto', 'some structure')"
        )

    def test_s3_build_function_call_azure_without_structure(self):
        res = build_function_call(
            "https://tomposthogtest.blob.core.windows.net/somecontainer/path/to/file.parquet",
            DataWarehouseTable.TableFormat.Parquet,
            "tomposthogtest",
            "blah",
            None,
            None,
        )

        assert (
            res
            == "azureBlobStorage('https://tomposthogtest.blob.core.windows.net', 'somecontainer', 'path/to/file.parquet', 'tomposthogtest', 'blah', 'Parquet', 'auto')"
        )

    def test_s3_build_function_call_azure_with_context(self):
        self._init_database()

        res = build_function_call(
            "https://tomposthogtest.blob.core.windows.net/somecontainer/path/to/file.parquet",
            DataWarehouseTable.TableFormat.Parquet,
            "tomposthogtest",
            "blah",
            None,
            self.context,
        )

        assert (
            res
            == "azureBlobStorage(%(hogql_val_0_sensitive)s, %(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s, %(hogql_val_5)s, 'auto')"
        )
