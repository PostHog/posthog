from datetime import date, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.retention_actor_sql import ALL_EVENTS_KIND, SHARDED_RETENTION_ACTOR_TABLE

_EPOCH = date(1970, 1, 1)


def _days_to_dates(day_numbers: list[int]) -> list[str]:
    return [(_EPOCH + timedelta(days=int(d))).isoformat() for d in sorted(day_numbers)]


class TestRetentionActorTable(ClickhouseTestMixin, BaseTest):
    """Proves the read combinators (minMerge / groupUniqArrayMerge) work through HogQL over the
    AggregateFunction state columns, and that the states compose across separate inserts — the
    incremental-merge property the whole design relies on."""

    def _insert_state(self, actor_id: str, ts: str, kind: str = "$pageview") -> None:
        # One state row for (actor, ts): minState of the timestamp + groupUniqArrayState of its
        # absolute day-number. Re-inserting for the same actor must merge, not duplicate.
        sync_execute(
            f"""
            INSERT INTO {SHARDED_RETENTION_ACTOR_TABLE()} (team_id, kind, actor_id, first_seen, active_days)
            SELECT
                %(team_id)s,
                %(kind)s,
                toUUID(%(actor_id)s),
                minState(toDateTime64(%(ts)s, 6, 'UTC')),
                groupUniqArrayState(toUInt32(toDate(toDateTime64(%(ts)s, 6, 'UTC'))))
            """,
            {"team_id": self.team.pk, "kind": kind, "actor_id": actor_id, "ts": ts},
        )

    def _read(self, kind: str = "$pageview"):
        result = execute_hogql_query(
            """
            SELECT
                actor_id,
                minMerge(first_seen) AS first_ts,
                arraySort(groupUniqArrayMerge(active_days)) AS days
            FROM posthog.retention_actor
            WHERE team_id = {team_id} AND kind = {kind}
            GROUP BY actor_id
            ORDER BY actor_id
            """,
            team=self.team,
            placeholders={"team_id": ast.Constant(value=self.team.pk), "kind": ast.Constant(value=kind)},
        )
        return result.results or []

    def test_minmerge_and_groupuniqarraymerge_compose_across_inserts(self):
        actor_a = "00000000-0000-0000-0000-0000000000a1"
        actor_b = "00000000-0000-0000-0000-0000000000b2"

        # Actor A active on two days, inserted as separate state rows — must merge into one actor
        # with the earlier first_ts and the union of days.
        self._insert_state(actor_a, "2024-01-10 09:00:00")
        self._insert_state(actor_a, "2024-01-12 23:30:00")
        # A later, higher timestamp on day 10 loses the min but keeps its day in the set.
        self._insert_state(actor_a, "2024-01-10 18:00:00")
        # A separate actor stays isolated.
        self._insert_state(actor_b, "2024-01-11 12:00:00")

        rows = self._read()
        self.assertEqual(len(rows), 2)

        a_id, a_first_ts, a_days = rows[0]
        self.assertEqual(str(a_id), actor_a)
        self.assertEqual(a_first_ts.strftime("%Y-%m-%d %H:%M:%S"), "2024-01-10 09:00:00")
        self.assertEqual(_days_to_dates(a_days), ["2024-01-10", "2024-01-12"])

        b_id, b_first_ts, b_days = rows[1]
        self.assertEqual(str(b_id), actor_b)
        self.assertEqual(b_first_ts.strftime("%Y-%m-%d %H:%M:%S"), "2024-01-11 12:00:00")
        self.assertEqual(_days_to_dates(b_days), ["2024-01-11"])

    def test_all_events_kind_is_isolated_from_pageview(self):
        actor = "00000000-0000-0000-0000-0000000000c3"
        self._insert_state(actor, "2024-02-01 00:00:00", kind="$pageview")
        self._insert_state(actor, "2024-02-05 00:00:00", kind=ALL_EVENTS_KIND)

        self.assertEqual(_days_to_dates(self._read(kind="$pageview")[0][2]), ["2024-02-01"])
        self.assertEqual(_days_to_dates(self._read(kind=ALL_EVENTS_KIND)[0][2]), ["2024-02-05"])
