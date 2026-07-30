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
            # A column named like a blocked table function is an identifier, not a call — allowed.
            ("column_named_url", "SELECT url FROM events"),
            ("column_named_file", "SELECT file, count() FROM events"),
            # A column named `settings` is not a SETTINGS clause (no trailing `<name> =`).
            ("column_named_settings", "SELECT settings FROM events"),
            ("settings_in_where", "SELECT * FROM events WHERE settings = 'x'"),
            ("settings_as_alias", "SELECT 1 AS settings, 2 AS x"),
        ]
    )
    def test_allows_read_only(self, _name, sql):
        self.assertEqual(ensure_read_only_raw_clickhouse_statement(sql), sql)

    @parameterized.expand(
        [
            ("max_block_size", "SELECT * FROM numbers(10) SETTINGS max_block_size=1000000000"),
            ("max_execution_time", "SELECT 1 SETTINGS max_execution_time=0"),
            ("multiple", "SELECT 1 SETTINGS max_execution_time = 0, max_block_size = 1"),
        ]
    )
    def test_rejects_settings_clause(self, _name, sql):
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_clickhouse_statement(sql)

    @parameterized.expand(
        [
            ("url_ssrf", "SELECT * FROM url('http://169.254.169.254/latest/meta-data/', RawBLOB)"),
            ("s3", "SELECT * FROM s3('http://x/f.csv')"),
            ("remote", "SELECT * FROM remote('other-host', db.t)"),
            ("mysql", "SELECT * FROM mysql('h:3306', 'db', 't', 'u', 'p')"),
            ("postgresql", "SELECT * FROM postgresql('h:5432', 'db', 't', 'u', 'p')"),
            ("file", "SELECT * FROM file('/etc/passwd', 'LineAsString')"),
            ("executable", "SELECT * FROM executable('script.sh', 'TabSeparated', 'x String')"),
            # Nested inside a subquery — the whole tree is walked.
            ("nested", "SELECT * FROM (SELECT * FROM url('http://x'))"),
            ("uppercase", "SELECT * FROM URL('http://x')"),
            # `*Cluster` twins read remotely just like their base function.
            ("iceberg_cluster", "SELECT * FROM icebergCluster('c', 'http://169.254.169.254/')"),
            ("delta_lake_cluster", "SELECT * FROM deltaLakeCluster('c', 'http://x')"),
            # merge() reads across every table the server can see; dictionary() can be remote-backed.
            ("merge", "SELECT * FROM merge('.*', '.*')"),
            ("dictionary", "SELECT * FROM dictionary('dict')"),
            # Quoted callees must still be caught — a double-quoted name doesn't parse as a Function.
            ("double_quoted_remote", "SELECT * FROM \"remote\"('other-host', db.t)"),
            ("backtick_remote", "SELECT * FROM `remote`('other-host', db.t)"),
        ]
    )
    def test_rejects_dangerous_table_functions(self, _name, sql):
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_clickhouse_statement(sql)

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
        rows, column_names, column_types = _fetch_capped_clickhouse_rows(client, "SELECT n FROM t", None, 600)
        self.assertEqual(rows, [(1,), (2,), (3,)])
        self.assertEqual(column_names, ["n"])
        self.assertEqual(column_types, ["Int64"])

    def test_raises_when_result_exceeds_cap(self):
        # The streaming guard trips one row past the cap — the memory-exhaustion path a raw
        # unbounded SELECT hits. Patch the cap small so the test doesn't allocate a million rows.
        client = self._stream_client([[(0,), (1,)], [(2,), (3,)]])
        with patch("posthog.hogql.direct_sql.clickhouse_adapter.DIRECT_CLICKHOUSE_MAX_ROWS", 3):
            with self.assertRaisesRegex(ExposedHogQLError, "Add a LIMIT clause"):
                _fetch_capped_clickhouse_rows(client, "SELECT n FROM t", None, 600)

    def test_raises_when_deadline_exceeded(self):
        # A raw query can set SETTINGS max_execution_time=0 and dribble out tiny blocks so the
        # socket timeout never fires; the wall-clock deadline is what stops it pinning the worker.
        client = self._stream_client([[(1,)], [(2,)]])
        with patch("posthog.hogql.direct_sql.clickhouse_adapter.perf_counter", side_effect=[0.0, 700.0]):
            with self.assertRaisesRegex(ExposedHogQLError, "execution time limit"):
                _fetch_capped_clickhouse_rows(client, "SELECT n FROM t", None, 600)

    def test_passes_parameters_through(self):
        client = self._stream_client([[(1,)]])
        params: dict[str, Any] = {"team_id": 1}
        _fetch_capped_clickhouse_rows(client, "SELECT n FROM t WHERE team = %(team_id)s", params, 600)
        client.query_row_block_stream.assert_called_once_with(
            "SELECT n FROM t WHERE team = %(team_id)s", parameters=params
        )
