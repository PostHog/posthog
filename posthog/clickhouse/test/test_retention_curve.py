from datetime import date

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.retention_curve_sql import ALL_EVENTS_KIND, DISTRIBUTED_RETENTION_CURVE_TABLE


class TestRetentionCurveTable(ClickhouseTestMixin, APIBaseTest):
    def _insert(self, person_id, kind, first_seen_day, active_offsets):
        sync_execute(
            f"""
            INSERT INTO {DISTRIBUTED_RETENTION_CURVE_TABLE()}
            (team_id, kind, person_id, first_seen_day, active_offsets)
            VALUES (%(team_id)s, %(kind)s, %(person_id)s, %(first_seen_day)s, %(active_offsets)s)
            """,
            {
                "team_id": self.team.pk,
                "kind": kind,
                "person_id": person_id,
                "first_seen_day": first_seen_day,
                "active_offsets": active_offsets,
            },
        )

    def test_stores_and_reads_a_person_curve_via_hogql(self):
        person_id = "00000000-0000-0000-0000-0000000000a1"
        self._insert(person_id, "$pageview", date(2023, 9, 1), [0, 1, 3, 30])
        # A second person on a different kind confirms the kind filter isolates rows.
        self._insert("00000000-0000-0000-0000-0000000000b2", ALL_EVENTS_KIND, date(2023, 9, 2), [0, 5])

        response = execute_hogql_query(
            """
            SELECT person_id, first_seen_day, active_offsets
            FROM posthog.retention_curve
            WHERE team_id = {team_id} AND kind = '$pageview'
            """,
            placeholders={"team_id": ast.Constant(value=self.team.pk)},
            team=self.team,
        )

        self.assertEqual(len(response.results), 1)
        row = response.results[0]
        self.assertEqual(str(row[0]), person_id)
        self.assertEqual(row[1], date(2023, 9, 1))
        self.assertEqual(list(row[2]), [0, 1, 3, 30])

    def test_active_offsets_array_column_reads_as_array(self):
        self._insert("00000000-0000-0000-0000-0000000000c3", "$pageview", date(2023, 9, 1), [0, 2, 9])

        response = execute_hogql_query(
            """
            SELECT arrayJoin(active_offsets) AS offset
            FROM posthog.retention_curve
            WHERE team_id = {team_id} AND kind = '$pageview'
            ORDER BY offset
            """,
            placeholders={"team_id": ast.Constant(value=self.team.pk)},
            team=self.team,
        )

        self.assertEqual([r[0] for r in response.results], [0, 2, 9])
