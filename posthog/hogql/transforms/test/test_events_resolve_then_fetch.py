import re
from datetime import datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query


def _normalize(sql: str) -> str:
    sql = re.sub(r"%\(hogql_val_\d+\)s", "hogval", sql)
    return re.sub(r"\s+", " ", sql)


class TestEventsResolveThenFetchRewrite(ClickhouseTestMixin, BaseTest):
    def _print(self, select: str) -> str:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        sql, _ = prepare_and_print_ast(parse_select(select), context, "clickhouse")
        return _normalize(sql)

    def _scans(self, sql: str) -> int:
        return sql.count("FROM events")

    def test_wide_star_scan_is_split(self):
        sql = self._print("SELECT * FROM events WHERE event = 'x' ORDER BY timestamp DESC LIMIT 100")
        # Inner narrow resolve + outer point-fetch == two scans of the events table.
        assert self._scans(sql) == 2
        # The outer prefilter matches the (timestamp, uuid) identity pair.
        assert "events.uuid" in sql
        assert "in(" in sql or "IN (" in sql
        # Inner orders by timestamp; when the timestamp_order_by rewrite (a separate optimization) is also
        # present it further rewrites this to read in primary-key order, but this transform does not require it.
        assert "events.timestamp" in sql

    @parameterized.expand(
        [
            ("properties_blob", "SELECT properties FROM events ORDER BY timestamp DESC LIMIT 10"),
            ("elements_chain", "SELECT elements_chain FROM events ORDER BY timestamp DESC LIMIT 10"),
            ("property_extraction", "SELECT properties.$foo FROM events ORDER BY timestamp DESC LIMIT 10"),
            ("with_offset", "SELECT * FROM events ORDER BY timestamp DESC LIMIT 10 OFFSET 5"),
            ("timezone_wrapped_order", "SELECT * FROM events ORDER BY toTimeZone(timestamp, 'UTC') DESC LIMIT 10"),
            ("ascending", "SELECT * FROM events ORDER BY timestamp ASC LIMIT 10"),
            # Any order that doesn't sort by a raw wide column qualifies (matches the runner's breadth) — the
            # inner stays narrow even when it can't early-terminate.
            ("non_leading_timestamp", "SELECT * FROM events ORDER BY event ASC, timestamp DESC LIMIT 10"),
            ("non_timestamp_order", "SELECT * FROM events ORDER BY event DESC LIMIT 10"),
            ("created_at_order", "SELECT * FROM events ORDER BY created_at DESC LIMIT 10"),
            ("function_wrapped_order", "SELECT * FROM events ORDER BY toStartOfHour(timestamp) DESC LIMIT 10"),
            ("property_extraction_order", "SELECT * FROM events ORDER BY properties.$foo DESC LIMIT 10"),
        ]
    )
    def test_qualifying_wide_scans_are_split(self, _name: str, select: str):
        assert self._scans(self._print(select)) == 2

    def test_lazy_person_reference_still_splits(self):
        # `person` is a lazy join at parse time, so the source is still a single bare events table.
        sql = self._print(
            "SELECT properties, person.properties.email FROM events "
            "WHERE person.properties.foo = 'x' ORDER BY timestamp DESC LIMIT 10"
        )
        assert self._scans(sql) == 2

    def test_split_inside_subquery(self):
        sql = self._print(
            "SELECT x.properties FROM "
            "(SELECT properties, timestamp, uuid FROM events ORDER BY timestamp DESC LIMIT 100) AS x"
        )
        assert self._scans(sql) == 2

    @parameterized.expand(
        [
            ("narrow_projection", "SELECT uuid, event FROM events ORDER BY timestamp DESC LIMIT 100"),
            ("no_limit", "SELECT * FROM events ORDER BY timestamp DESC"),
            (
                "aggregation",
                "SELECT properties, count() FROM events GROUP BY properties ORDER BY timestamp DESC LIMIT 10",
            ),
            ("distinct", "SELECT DISTINCT properties FROM events ORDER BY timestamp DESC LIMIT 10"),
            ("window_function", "SELECT properties, row_number() OVER (ORDER BY timestamp) FROM events LIMIT 10"),
            # Ordering by a raw wide column would need that column in the inner sort — the thing we avoid.
            ("order_by_raw_properties", "SELECT * FROM events ORDER BY properties DESC LIMIT 10"),
            ("order_by_elements_chain", "SELECT * FROM events ORDER BY elements_chain DESC LIMIT 10"),
            # ORDER BY references a SELECT alias the narrow inner wouldn't have, so it can't be cloned in.
            ("order_by_select_alias", "SELECT properties.foo AS label FROM events ORDER BY label ASC LIMIT 10"),
            ("no_order_by", "SELECT * FROM events LIMIT 10"),
            ("with_fill", "SELECT * FROM events ORDER BY timestamp DESC WITH FILL LIMIT 10"),
            ("not_events_table", "SELECT * FROM persons ORDER BY created_at DESC LIMIT 10"),
        ]
    )
    def test_non_qualifying_scans_are_not_split(self, _name: str, select: str):
        assert self._scans(self._print(select)) <= 1

    def test_huge_limit_is_not_split(self):
        # A limit beyond the standard returned-rows ceiling would just double-scan most of the table.
        assert self._scans(self._print("SELECT * FROM events ORDER BY timestamp DESC LIMIT 200000")) == 1

    def test_outer_keeps_the_filter(self):
        # The crux of the superset: the outer WHERE keeps the original predicate (so sort-key granule pruning
        # survives) and ANDs in the (timestamp, uuid) prefilter — it does not replace it. The predicate appears
        # twice: once in the narrow inner resolve, once in the kept outer filter.
        sql = self._print("SELECT properties FROM events WHERE event = 'x' ORDER BY timestamp DESC LIMIT 10")
        assert self._scans(sql) == 2
        assert sql.count("events.event") == 2
        # The identity-pair prefilter is on the outer too.
        assert "events.uuid" in sql

    def test_already_resolve_fetched_is_not_rewrapped(self):
        # A hand-written `uuid IN (...)` split is left alone (its narrow inner never qualifies), so exactly two
        # scans remain rather than a third nested wrap.
        sql = self._print(
            "SELECT * FROM events WHERE uuid IN (SELECT uuid FROM events ORDER BY timestamp DESC LIMIT 100) "
            "ORDER BY timestamp DESC LIMIT 100"
        )
        assert self._scans(sql) == 2


class TestEventsResolveThenFetchCorrectness(ClickhouseTestMixin, BaseTest):
    INSTANTS = [
        ("u0", datetime(2024, 2, 10, 23, 0)),
        ("u1", datetime(2024, 2, 11, 2, 0)),
        ("u2", datetime(2024, 2, 11, 9, 0)),
        ("u3", datetime(2024, 2, 12, 20, 0)),
        ("u4", datetime(2024, 2, 12, 21, 30)),
    ]

    def setUp(self):
        super().setUp()
        for distinct_id, ts in self.INSTANTS:
            _create_event(
                team=self.team,
                distinct_id=distinct_id,
                event="$pageview",
                timestamp=ts,
                properties={"marker": distinct_id},
            )
        flush_persons_and_events()

    def _wide(self, select: str) -> tuple[list, str]:
        response = execute_hogql_query(select, team=self.team)
        assert response.results is not None
        return response.results, re.sub(r"\s+", " ", response.clickhouse or "")

    def test_wide_query_is_split_and_ordered(self):
        results, sql = self._wide("SELECT distinct_id, properties.marker FROM events ORDER BY timestamp DESC LIMIT 3")
        assert sql.count("FROM events") == 2
        assert [row[0] for row in results] == ["u4", "u3", "u2"]
        # The wide column is point-fetched correctly for the resolved rows.
        assert [row[1] for row in results] == ["u4", "u3", "u2"]

    def test_split_matches_unsplit_rows(self):
        wide, wide_sql = self._wide("SELECT distinct_id, properties FROM events ORDER BY timestamp ASC LIMIT 4")
        narrow, narrow_sql = self._wide("SELECT distinct_id FROM events ORDER BY timestamp ASC LIMIT 4")
        assert wide_sql.count("FROM events") == 2
        assert narrow_sql.count("FROM events") == 1
        assert [row[0] for row in wide] == [row[0] for row in narrow] == ["u0", "u1", "u2", "u3"]

    def test_offset_pagination_is_correct(self):
        results, sql = self._wide("SELECT distinct_id, properties FROM events ORDER BY timestamp DESC LIMIT 2 OFFSET 1")
        assert sql.count("FROM events") == 2
        assert [row[0] for row in results] == ["u3", "u2"]

    def test_filtered_wide_query_is_correct(self):
        results, sql = self._wide(
            "SELECT distinct_id, properties FROM events WHERE distinct_id != 'u4' ORDER BY timestamp DESC LIMIT 2"
        )
        assert sql.count("FROM events") == 2
        assert [row[0] for row in results] == ["u3", "u2"]
