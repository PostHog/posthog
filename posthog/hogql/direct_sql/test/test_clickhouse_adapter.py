from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.direct_clickhouse_table import DirectClickHouseTable
from posthog.hogql.direct_sql.clickhouse_adapter import (
    _fetch_capped_clickhouse_rows,
    ensure_read_only_raw_clickhouse_statement,
)
from posthog.hogql.errors import ExposedHogQLError, QueryError


class TestDirectClickHouseTable(SimpleTestCase):
    def _table(self, database: str) -> DirectClickHouseTable:
        return DirectClickHouseTable(
            name="events",
            fields={},
            clickhouse_database=database,
            clickhouse_table_name="events",
            external_data_source_id="src",
        )

    def test_renders_escaped_database_and_table(self):
        self.assertEqual(self._table("mydb").to_printed_clickhouse(None), "mydb.events")

    def test_renders_table_only_when_no_database(self):
        self.assertEqual(self._table("").to_printed_clickhouse(None), "events")

    def test_escapes_special_identifiers(self):
        table = DirectClickHouseTable(
            name="t",
            fields={},
            clickhouse_database="my db",
            clickhouse_table_name="weird.name",
            external_data_source_id="s",
        )
        # backtick-escaped because they contain a space / dot
        self.assertEqual(table.to_printed_clickhouse(None), "`my db`.`weird.name`")

    def test_refuses_other_dialects(self):
        table = self._table("mydb")
        with self.assertRaises(QueryError):
            table.to_printed_postgres(None)
        with self.assertRaises(QueryError):
            table.to_printed_mysql(None)


class TestClickHouseReadOnlyGuard(SimpleTestCase):
    @parameterized.expand(
        [
            ("select", "SELECT * FROM events"),
            ("with_cte", "WITH x AS (SELECT 1) SELECT * FROM x"),
            ("lowercase", "select count() from events"),
            ("leading_comment", "-- hi\nSELECT 1"),
        ]
    )
    def test_allows_read_only(self, _name, sql):
        self.assertEqual(ensure_read_only_raw_clickhouse_statement(sql), sql)

    @parameterized.expand(
        [
            ("insert", "INSERT INTO events VALUES (1)"),
            ("alter", "ALTER TABLE events DELETE WHERE 1"),
            ("drop", "DROP TABLE events"),
            ("truncate", "TRUNCATE TABLE events"),
            ("system", "SYSTEM RELOAD DICTIONARIES"),
            ("multi_statement", "SELECT 1; DROP TABLE events"),
            # A first-keyword check treated these as read-only because they open with WITH/SELECT,
            # but the driver still runs the embedded write — the whole statement must be inspected.
            ("with_prefixed_insert", "WITH 1 AS x INSERT INTO target SELECT x"),
            ("write_in_subquery", "SELECT * FROM (INSERT INTO events VALUES (1))"),
        ]
    )
    def test_rejects_writes(self, _name, sql):
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_clickhouse_statement(sql)


class TestClickHouseRowCap(SimpleTestCase):
    def _stream_client(self, blocks: list[list[tuple]]) -> MagicMock:
        stream = MagicMock()
        stream.source.column_names = ["n"]
        stream.source.column_types = ["Int64"]
        stream.__iter__.return_value = iter(blocks)
        client = MagicMock()
        client.query_row_block_stream.return_value.__enter__.return_value = stream
        client.query_row_block_stream.return_value.__exit__.return_value = False
        return client

    def test_returns_rows_and_types_under_cap(self):
        client = self._stream_client([[(1,), (2,)], [(3,)]])
        rows, column_names, column_types = _fetch_capped_clickhouse_rows(client, "SELECT n FROM t", None)
        self.assertEqual(rows, [(1,), (2,), (3,)])
        self.assertEqual(column_names, ["n"])
        self.assertEqual(column_types, ["Int64"])

    def test_raises_when_result_exceeds_cap(self):
        # The streaming guard trips one row past the cap — the memory-exhaustion path a raw
        # unbounded SELECT hits. Patch the cap small so the test doesn't allocate a million rows.
        client = self._stream_client([[(0,), (1,)], [(2,), (3,)]])
        with patch("posthog.hogql.direct_sql.clickhouse_adapter.DIRECT_CLICKHOUSE_MAX_ROWS", 3):
            with self.assertRaisesRegex(ExposedHogQLError, "Add a LIMIT clause"):
                _fetch_capped_clickhouse_rows(client, "SELECT n FROM t", None)

    def test_passes_parameters_through(self):
        client = self._stream_client([[(1,)]])
        params: dict[str, Any] = {"team_id": 1}
        _fetch_capped_clickhouse_rows(client, "SELECT n FROM t WHERE team = %(team_id)s", params)
        client.query_row_block_stream.assert_called_once_with(
            "SELECT n FROM t WHERE team = %(team_id)s", parameters=params
        )
