from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.direct_clickhouse_table import DirectClickHouseTable
from posthog.hogql.direct_sql.clickhouse_adapter import ensure_read_only_raw_clickhouse_statement
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
        ]
    )
    def test_rejects_writes(self, _name, sql):
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_clickhouse_statement(sql)
