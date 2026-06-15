from datetime import date, datetime, timedelta

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.retention.retention_actor_materialize import (
    ALL_EVENTS_KIND,
    HORIZON_DAYS,
    PAGEVIEW_KIND,
    ensure_retention_actor,
    materialize_retention_actor,
)

_EPOCH = date(1970, 1, 1)


def _days_to_dates(day_numbers: list[int]) -> list[str]:
    return [(_EPOCH + timedelta(days=int(d))).isoformat() for d in sorted(day_numbers)]


class TestRetentionActorMaterialize(ClickhouseTestMixin, APIBaseTest):
    ACTOR_A = "00000000-0000-0000-0000-0000000000a1"
    ACTOR_B = "00000000-0000-0000-0000-0000000000b2"

    def _event(self, person_id: str, ts: str, event: str = "$pageview") -> None:
        _create_event(team=self.team, event=event, distinct_id=person_id, timestamp=ts, person_id=person_id)

    def _read(self, kind: str = PAGEVIEW_KIND):
        result = execute_hogql_query(
            """
            SELECT actor_id, minMerge(first_seen) AS first_ts, arraySort(groupUniqArrayMerge(active_days)) AS days
            FROM posthog.retention_actor
            WHERE team_id = {team_id} AND kind = {kind}
            GROUP BY actor_id
            ORDER BY actor_id
            """,
            team=self.team,
            placeholders={"team_id": ast.Constant(value=self.team.pk), "kind": ast.Constant(value=kind)},
        )
        return result.results or []

    def test_materialize_pageview_cohort_and_returns(self):
        self._event(self.ACTOR_A, "2024-01-10 09:00:00")
        self._event(self.ACTOR_A, "2024-01-12 23:30:00")
        self._event(self.ACTOR_A, "2024-01-15 00:00:00", event="$autocapture")  # not a pageview — excluded
        self._event(self.ACTOR_B, "2024-01-11 12:00:00")
        flush_persons_and_events()

        materialize_retention_actor(self.team, PAGEVIEW_KIND)
        rows = self._read()

        self.assertEqual(len(rows), 2)
        a_id, a_first, a_days = rows[0]
        self.assertEqual(str(a_id), self.ACTOR_A)
        self.assertEqual(a_first.strftime("%Y-%m-%d %H:%M:%S"), "2024-01-10 09:00:00")
        self.assertEqual(_days_to_dates(a_days), ["2024-01-10", "2024-01-12"])
        self.assertEqual(_days_to_dates(rows[1][2]), ["2024-01-11"])

    def test_all_events_kind_includes_non_pageview(self):
        self._event(self.ACTOR_A, "2024-02-01 00:00:00", event="$pageview")
        self._event(self.ACTOR_A, "2024-02-03 00:00:00", event="$autocapture")
        flush_persons_and_events()

        materialize_retention_actor(self.team, ALL_EVENTS_KIND)
        self.assertEqual(_days_to_dates(self._read(kind=ALL_EVENTS_KIND)[0][2]), ["2024-02-01", "2024-02-03"])

    def test_days_beyond_horizon_are_dropped(self):
        first = datetime(2022, 1, 1, 0, 0, 0)
        beyond = first + timedelta(days=HORIZON_DAYS + 5)
        within = first + timedelta(days=HORIZON_DAYS - 5)
        for ts in (first, within, beyond):
            self._event(self.ACTOR_A, ts.strftime("%Y-%m-%d %H:%M:%S"))
        flush_persons_and_events()

        materialize_retention_actor(self.team, PAGEVIEW_KIND)
        days = _days_to_dates(self._read()[0][2])
        self.assertIn(first.date().isoformat(), days)
        self.assertIn(within.date().isoformat(), days)
        self.assertNotIn(beyond.date().isoformat(), days)

    def test_ensure_materialises_then_is_fresh(self):
        self._event(self.ACTOR_A, "2024-03-01 00:00:00")
        flush_persons_and_events()

        self.assertTrue(ensure_retention_actor(self.team, PAGEVIEW_KIND).ready)
        self.assertEqual(_days_to_dates(self._read()[0][2]), ["2024-03-01"])
        # Second call is served from the freshness marker without re-scanning.
        self.assertTrue(ensure_retention_actor(self.team, PAGEVIEW_KIND).ready)

    def test_overrides_resolved_at_insert(self):
        # Two distinct_ids with separate person_ids that then merge: did_b -> person of did_a.
        p1 = "00000000-0000-0000-0000-0000000000d1"
        p2 = "00000000-0000-0000-0000-0000000000d2"
        _create_person(team=self.team, distinct_ids=["did_a"], uuid=p1)
        _create_person(team=self.team, distinct_ids=["did_b"], uuid=p2)
        _create_event(
            team=self.team, event="$pageview", distinct_id="did_a", timestamp="2024-04-01 00:00:00", person_id=p1
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="did_b", timestamp="2024-04-03 00:00:00", person_id=p2
        )
        flush_persons_and_events()
        create_person_id_override_by_distinct_id(distinct_id_from="did_b", distinct_id_to="did_a", team_id=self.team.pk)

        materialize_retention_actor(self.team, PAGEVIEW_KIND)
        rows = self._read()

        # The merged actor is counted once (under p1) with both days — not two orphaned actors.
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0][0]), p1)
        self.assertEqual(_days_to_dates(rows[0][2]), ["2024-04-01", "2024-04-03"])
