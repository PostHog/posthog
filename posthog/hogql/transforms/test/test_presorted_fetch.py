import re

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.query import HogQLQueryExecutor, execute_hogql_query


class TestPresortedFetch(ClickhouseTestMixin, APIBaseTest):
    def _ch_sql(self, query: str, optimize: bool = True) -> str:
        modifiers = HogQLQueryModifiers(optimizePresortedFetch=optimize)
        sql, _ = HogQLQueryExecutor(
            query=query, team=self.team, modifiers=modifiers, pretty=False
        ).generate_clickhouse_sql()
        return sql

    def _assert_rewritten(self, sql: str) -> None:
        # An identifier-only subquery selecting `<table>.uuid AS uuid` is the rewrite's fingerprint.
        # The table prefix is the alias when the outer query aliases events.
        assert re.search(r"\(SELECT \w+\.uuid AS uuid", sql), sql
        assert sql.count("FROM events") >= 2, sql

    def _assert_not_rewritten(self, sql: str) -> None:
        assert re.search(r"\(SELECT \w+\.uuid AS uuid", sql) is None, sql

    def test_rewrites_select_properties_order_by_timestamp(self):
        sql = self._ch_sql("SELECT uuid, properties FROM events ORDER BY timestamp DESC LIMIT 100")
        self._assert_rewritten(sql)
        assert "LIMIT 100" in sql

    def test_rewrites_select_star(self):
        self._assert_rewritten(self._ch_sql("SELECT * FROM events ORDER BY timestamp LIMIT 50"))

    def test_rewrites_select_elements_chain(self):
        self._assert_rewritten(self._ch_sql("SELECT elements_chain FROM events ORDER BY timestamp LIMIT 10"))

    def test_rewrites_with_aliased_table(self):
        self._assert_rewritten(self._ch_sql("SELECT e.properties FROM events AS e ORDER BY e.timestamp LIMIT 10"))

    def test_rewrites_property_extraction_in_order_by(self):
        # Sorting by an extracted value (not the raw blob) is allowed.
        self._assert_rewritten(self._ch_sql("SELECT properties FROM events ORDER BY properties.$browser DESC LIMIT 10"))

    def test_inner_limit_includes_offset(self):
        sql = self._ch_sql("SELECT uuid, properties FROM events ORDER BY timestamp LIMIT 10 OFFSET 5")
        self._assert_rewritten(sql)
        # Inner must fetch limit + offset rows; outer keeps limit/offset.
        assert "LIMIT 15" in sql
        assert "OFFSET 5" in sql

    @parameterized.expand(
        [
            ("no_wide_column", "SELECT uuid, timestamp, event FROM events ORDER BY timestamp LIMIT 100"),
            ("no_order_by", "SELECT uuid, properties FROM events LIMIT 100"),
            ("aggregation", "SELECT count(), properties FROM events GROUP BY properties ORDER BY count() LIMIT 100"),
            ("distinct", "SELECT DISTINCT properties FROM events ORDER BY properties LIMIT 100"),
            ("raw_properties_in_order_by", "SELECT properties FROM events ORDER BY properties LIMIT 100"),
            ("elements_chain_in_order_by", "SELECT properties FROM events ORDER BY elements_chain LIMIT 100"),
            ("limit_above_cap", "SELECT uuid, properties FROM events ORDER BY timestamp LIMIT 10001"),
        ]
    )
    def test_not_rewritten(self, _name: str, query: str):
        self._assert_not_rewritten(self._ch_sql(query))

    def test_disabled_by_modifier(self):
        self._assert_not_rewritten(
            self._ch_sql("SELECT uuid, properties FROM events ORDER BY timestamp DESC LIMIT 100", optimize=False)
        )

    def test_cte_named_events_not_rewritten(self):
        # `events` here is a CTE, not the real table, so the rewrite must not fire.
        sql = self._ch_sql(
            "WITH events AS (SELECT 1 AS uuid, 2 AS properties) "
            "SELECT uuid, properties FROM events ORDER BY uuid LIMIT 10"
        )
        self._assert_not_rewritten(sql)

    def _make_events(self, count: int) -> None:
        for i in range(count):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"d{i}",
                timestamp=f"2024-01-01 00:00:{i:02d}",
                properties={"idx": i},
            )
        flush_persons_and_events()

    def _results(self, query: str, optimize: bool) -> list:
        response = execute_hogql_query(
            query, self.team, modifiers=HogQLQueryModifiers(optimizePresortedFetch=optimize), pretty=False
        )
        return response.results or []

    def test_parity_results_identical(self):
        self._make_events(10)
        query = "SELECT uuid, properties.idx FROM events ORDER BY timestamp DESC LIMIT 4"
        assert self._results(query, optimize=True) == self._results(query, optimize=False)

    def test_parity_with_offset(self):
        self._make_events(10)
        query = "SELECT properties.idx FROM events ORDER BY timestamp ASC LIMIT 3 OFFSET 4"
        on = self._results(query, optimize=True)
        off = self._results(query, optimize=False)
        assert on == off
        # Confirms the offset is applied once (not doubled): rows 4-6 of the ascending order.
        assert [int(row[0]) for row in on] == [4, 5, 6]
