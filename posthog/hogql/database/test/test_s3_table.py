from typing import Literal

from posthog.test.base import BaseTest
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import TableNode
from posthog.hogql.database.s3_table import build_function_call, compression_for_url_pattern
from posthog.hogql.database.test.tables import create_aapl_stock_s3_table
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team

from posthog.models.event.sql import DISTRIBUTED_EVENTS_JSON_TABLE

from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestS3Compression(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_file", "https://b.example.com/t/data.csv", "none"),
            ("no_extension", "https://b.example.com/t/data", "none"),
            ("folder", "https://b.example.com/t/", "none"),
            ("pinned_glob", "https://b.example.com/t/*.parquet", "none"),
            ("pinned_compressed_glob", "https://b.example.com/t/*.CSV.GZ", "gzip"),
            ("braces_before_the_extension", "https://b.example.com/t/{a,b}.json.zst", "zstd"),
            ("dotted_folder", "https://b.example.com/t.gz/data", "none"),
            ("open_glob", "https://b.example.com/t/*", None),
            ("recursive_glob", "https://b.example.com/t/**", None),
            ("glob_after_the_stem", "https://b.example.com/t/data_*", None),
            ("braces_in_the_extension", "https://b.example.com/t/*.{csv,csv.gz}", None),
            ("question_mark_in_the_extension", "https://b.example.com/t/data.cs?", None),
        ]
    )
    def test_compression_for_url_pattern(self, _name: str, url: str, expected: str | None) -> None:
        assert compression_for_url_pattern(url) == expected

    @parameterized.expand(
        [
            (
                "s3_without_structure",
                "https://b.example.com/t/*.csv.gz",
                None,
                "s3('https://b.example.com/t/*.csv.gz', 'key', 'secret', 'CSVWithNames', 'auto', 'gzip')",
            ),
            (
                "s3_with_structure",
                "https://b.example.com/t/*.csv.gz",
                "id String",
                "s3('https://b.example.com/t/*.csv.gz', 'key', 'secret', 'CSVWithNames', 'id String', 'gzip')",
            ),
            (
                "azure",
                "https://acct.blob.core.windows.net/c/t/*.csv.gz",
                "id String",
                "azureBlobStorage('https://acct.blob.core.windows.net', 'c', 't/*.csv.gz', 'key', 'secret', 'CSVWithNames', 'gzip', 'id String')",
            ),
        ]
    )
    def test_build_function_call_passes_an_explicit_codec(
        self, _name: str, url: str, structure: str | None, expected: str
    ) -> None:
        res = build_function_call(
            url, DataWarehouseTable.TableFormat.CSVWithNames, None, "key", "secret", structure, compression="gzip"
        )
        assert res == expected

    @parameterized.expand(
        [
            ("pinned", "https://b.example.com/t/export.csv.br", True),
            ("long_extension", "https://b.example.com/t/export.CSV.BROTLI", True),
            ("brace_alternative", "https://b.example.com/t/*.{csv,csv.br}", True),
            ("glob_after_the_extension", "https://b.example.com/t/*.br*", True),
            ("brace_alternative_across_folders", "https://b.example.com/{a/x.csv,b/y.br}", True),
            ("br_inside_a_brace_alternative", "https://b.example.com/t/{data.br,data.us}.csv", False),
            ("too_many_brace_expansions", "https://b.example.com/t/" + "{a,b}" * 40 + ".csv.br", True),
            ("lookalike_extension", "https://b.example.com/t/x.brand.csv", False),
            ("br_inside_the_name", "https://b.example.com/t/x.br.csv", False),
            ("br_host", "https://files.example.com.br/t/x.csv", False),
        ]
    )
    def test_build_function_call_rejects_brotli_files(self, _name: str, url: str, rejected: bool) -> None:
        if rejected:
            with self.assertRaisesMessage(ExposedHogQLError, "Brotli"):
                build_function_call(url, DataWarehouseTable.TableFormat.CSVWithNames, None, "key", "secret")
        else:
            build_function_call(url, DataWarehouseTable.TableFormat.CSVWithNames, None, "key", "secret")

    @parameterized.expand([(DataWarehouseTable.TableFormat.Delta,), (DataWarehouseTable.TableFormat.DeltaS3Wrapper,)])
    def test_build_function_call_reads_a_delta_table_in_a_br_folder(self, table_format: str) -> None:
        build_function_call("https://b.example.com/lake/table.br", table_format, None, "key", "secret")


class TestS3Table(BaseTest):
    def _events_from_sql(self) -> str:
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            return f"{DISTRIBUTED_EVENTS_JSON_TABLE} AS events"
        return "events"

    def _init_database(self):
        self.database = Database.create_for(team=self.team)
        self.database._add_warehouse_tables(
            TableNode(
                children={
                    "aapl_stock": TableNode(
                        name="aapl_stock",
                        table=create_aapl_stock_s3_table(),
                    ),
                    "aapl_stock_2": TableNode(
                        name="aapl_stock_2",
                        table=create_aapl_stock_s3_table(name="aapl_stock_2"),
                    ),
                }
            )
        )

        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=self.database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _select(self, query: str, dialect: Literal["hogql", "clickhouse"] = "clickhouse") -> str:
        return prepare_and_print_ast(parse_select(query), self.context, dialect=dialect)[0]

    def test_s3_table_select(self):
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
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
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
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
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
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
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
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
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
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
                f"SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM (SELECT * FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s)) AS aapl_stock JOIN {self._events_from_sql()} ON equals(aapl_stock.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
            )

    def test_s3_table_select_and_non_s3_join_first(self):
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
            self._init_database()
            with mock.patch("posthog.hogql.resolver.USE_GLOBAL_JOINS", True):
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
                    f"SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM {self._events_from_sql()} GLOBAL JOIN (SELECT * FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s)) AS aapl_stock ON equals(aapl_stock.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
                )

                clickhouse = self._select(
                    query="SELECT aapl_stock.High, aapl_stock.Low FROM events LEFT JOIN aapl_stock ON aapl_stock.High = events.event LIMIT 10",
                    dialect="clickhouse",
                )

                self.assertEqual(
                    clickhouse,
                    f"SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM {self._events_from_sql()} GLOBAL LEFT JOIN (SELECT * FROM s3(%(hogql_val_2_sensitive)s, %(hogql_val_3)s)) AS aapl_stock ON equals(aapl_stock.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
                )

                clickhouse = self._select(
                    query="SELECT aapl_stock.High, aapl_stock.Low FROM events RIGHT JOIN aapl_stock ON aapl_stock.High = events.event LIMIT 10",
                    dialect="clickhouse",
                )

                self.assertEqual(
                    clickhouse,
                    f"SELECT aapl_stock.High AS High, aapl_stock.Low AS Low FROM {self._events_from_sql()} GLOBAL RIGHT JOIN (SELECT * FROM s3(%(hogql_val_4_sensitive)s, %(hogql_val_5)s)) AS aapl_stock ON equals(aapl_stock.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
                )

    def test_s3_table_select_alias_escaped(self):
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
            self._init_database()

            self.database._add_warehouse_tables(
                TableNode(
                    children={
                        "random as (SELECT * FROM events), SELECT * FROM events --": TableNode(
                            name="random as (SELECT * FROM events), SELECT * FROM events --",
                            table=create_aapl_stock_s3_table(
                                name="random as (SELECT * FROM events), SELECT * FROM events --"
                            ),
                        )
                    }
                )
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
                f"SELECT `random as (SELECT * FROM events), SELECT * FROM events --`.High AS High, `random as (SELECT * FROM events), SELECT * FROM events --`.Low AS Low FROM (SELECT * FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s)) AS `random as (SELECT * FROM events), SELECT * FROM events --` JOIN {self._events_from_sql()} ON equals(`random as (SELECT * FROM events), SELECT * FROM events --`.High, events.event) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
            )

    def test_s3_table_select_table_name_bad_character(self):
        self._init_database()

        self.database._add_warehouse_tables(
            TableNode(
                children={
                    "some%(asd)sname": TableNode(
                        name="some%(asd)sname", table=create_aapl_stock_s3_table(name="some%(asd)sname")
                    ),
                }
            )
        )

        with self.assertRaises(ExposedHogQLError) as context:
            self._select(query='SELECT * FROM "some%(asd)sname" LIMIT 10', dialect="clickhouse")
            self.assertTrue("Alias \"some%(asd)sname\" contains unsupported character '%'" in str(context.exception))

    def test_s3_table_select_in(self):
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
            self._init_database()
            with mock.patch("posthog.hogql.resolver.USE_GLOBAL_JOINS", True):
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
                    f"SELECT events.uuid AS uuid, events.event AS event FROM {self._events_from_sql()} WHERE and(equals(events.team_id, {self.team.pk}), globalIn(events.event, (SELECT aapl_stock.Date AS Date FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s) AS aapl_stock))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
                )

    def test_s3_build_function_call_without_context(self):
        res = build_function_call(
            "http://url.com", DataWarehouseTable.TableFormat.Parquet, None, "key", "secret", None, None
        )
        assert res == "s3('http://url.com', 'key', 'secret', 'Parquet')"

    def test_s3_build_function_call_without_context_with_structure(self):
        res = build_function_call(
            "http://url.com", DataWarehouseTable.TableFormat.Parquet, None, "key", "secret", "some structure", None
        )
        assert res == "s3('http://url.com', 'key', 'secret', 'Parquet', 'some structure')"

    def test_s3_build_function_call_without_context_and_delta_format(self):
        res = build_function_call(
            "http://url.com", DataWarehouseTable.TableFormat.Delta, None, "key", "secret", None, None
        )
        assert res == "deltaLake('http://url.com', 'key', 'secret', 'Parquet')"

    def test_s3_build_function_call_without_context_and_deltaS3Wrapper_format(self):
        res = build_function_call(
            "http://url.com/folder", DataWarehouseTable.TableFormat.DeltaS3Wrapper, None, "key", "secret", None, None
        )
        assert res == "s3('http://url.com/folder__query/**.parquet', 'key', 'secret', 'Parquet')"

    def test_s3_build_function_call_without_context_and_deltaS3Wrapper_format_with_slash(self):
        res = build_function_call(
            "http://url.com/folder/", DataWarehouseTable.TableFormat.DeltaS3Wrapper, None, "key", "secret", None, None
        )
        assert res == "s3('http://url.com/folder__query/**.parquet', 'key', 'secret', 'Parquet')"

    def test_s3_build_function_call_without_context_and_deltaS3Wrapper_format_with_structure(self):
        res = build_function_call(
            "http://url.com/folder",
            DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            None,
            "key",
            "secret",
            "some structure",
            None,
        )
        assert res == "s3('http://url.com/folder__query/**.parquet', 'key', 'secret', 'Parquet', 'some structure')"

    def test_s3_build_function_call_without_context_and_delta_format_and_with_structure(self):
        res = build_function_call(
            "http://url.com", DataWarehouseTable.TableFormat.Delta, None, "key", "secret", "some structure", None
        )
        assert res == "deltaLake('http://url.com', 'key', 'secret', 'Parquet', 'some structure')"

    def test_s3_build_function_call_azure(self):
        res = build_function_call(
            "https://tomposthogtest.blob.core.windows.net/somecontainer/path/to/file.parquet",
            DataWarehouseTable.TableFormat.Parquet,
            None,
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
            None,
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
            None,
            "tomposthogtest",
            "blah",
            None,
            self.context,
        )

        assert (
            res
            == "azureBlobStorage(%(hogql_val_0_sensitive)s, %(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s, %(hogql_val_5)s, 'auto')"
        )

    def test_s3_build_function_call_with_large_table(self):
        res = build_function_call(
            "http://url.com",
            DataWarehouseTable.TableFormat.Parquet,
            None,
            "key",
            "secret",
            "some structure",
            None,
            4000.0,
        )
        assert res == "s3Cluster('posthog', 'http://url.com', 'key', 'secret', 'Parquet', 'some structure')"

    def test_s3_build_function_call_with_queryable_folder(self):
        res = build_function_call(
            "http://url.com/path/to/table_name",
            DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            "table_name__query_12345",
            "key",
            "secret",
            "some structure",
            None,
            10,
        )
        assert (
            res
            == "s3('http://url.com/path/to/table_name__query_12345/**.parquet', 'key', 'secret', 'Parquet', 'some structure')"
        )

    def test_s3_build_function_call_with_queryable_folder_and_cluster(self):
        res = build_function_call(
            "http://url.com/path/to/table_name",
            DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            "table_name__query_12345",
            "key",
            "secret",
            "some structure",
            None,
            4000,
        )
        assert (
            res
            == "s3Cluster('posthog', 'http://url.com/path/to/table_name__query_12345/**.parquet', 'key', 'secret', 'Parquet', 'some structure')"
        )

    def test_s3_build_function_call_with_debug_disabled(self):
        with (
            override_settings(DEBUG=False, TEST=False, USE_LOCAL_SETUP=False),
        ):
            res = build_function_call(
                "http://url.com/path/to/table_name",
                DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                "table_name__query_12345",
                None,
                None,
                "some structure",
                None,
                4000,
            )
            assert (
                res
                == "s3Cluster('posthog', 'http://url.com/path/to/table_name__query_12345/**.parquet', 'Parquet', 'some structure')"
            )
