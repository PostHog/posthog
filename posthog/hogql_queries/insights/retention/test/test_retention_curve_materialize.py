from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.retention_curve_sql import ALL_EVENTS_KIND, DISTRIBUTED_RETENTION_CURVE_TABLE
from posthog.hogql_queries.insights.retention.retention_curve_materialize import (
    HORIZON_DAYS,
    PAGEVIEW_KIND,
    ensure_retention_curve,
    materialize_retention_curve,
)


def _ts(year: int, month: int, day: int, hour: int = 5) -> str:
    return datetime(year, month, day, hour, tzinfo=UTC).isoformat()


class TestRetentionCurveMaterialize(ClickhouseTestMixin, APIBaseTest):
    def _curve_rows(self, kind):
        return sync_execute(
            f"""
            SELECT person_id, first_seen_day, active_offsets
            FROM {DISTRIBUTED_RETENTION_CURVE_TABLE()} FINAL
            WHERE team_id = %(team_id)s AND kind = %(kind)s
            ORDER BY first_seen_day
            """,
            {"team_id": self.team.pk, "kind": kind},
        )

    def test_first_seen_day_is_all_history(self):
        # The whole point of the curve: first_seen_day is the earliest qualifying day across
        # ALL history, and offsets are measured from it — even days far apart.
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp=_ts(2023, 9, 1))
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp=_ts(2023, 9, 10))
        flush_persons_and_events()

        materialize_retention_curve(self.team, PAGEVIEW_KIND)

        rows = self._curve_rows(PAGEVIEW_KIND)
        self.assertEqual(len(rows), 1)
        _person_id, first_seen_day, active_offsets = rows[0]
        self.assertEqual(first_seen_day, datetime(2023, 9, 1).date())
        self.assertEqual(list(active_offsets), [0, 9])

    def test_pageview_vs_all_events_kinds(self):
        # p1: pageviews on day 1 + a custom event on day 3 -> pageview curve [0]; all-events [0,2]
        # p2: only a custom event on day 1 -> no pageview row; all-events [0]
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        _create_person(team_id=self.team.pk, distinct_ids=["p2"])
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp=_ts(2023, 9, 1))
        _create_event(team=self.team, event="custom", distinct_id="p1", timestamp=_ts(2023, 9, 3))
        _create_event(team=self.team, event="custom", distinct_id="p2", timestamp=_ts(2023, 9, 1))
        flush_persons_and_events()

        materialize_retention_curve(self.team, PAGEVIEW_KIND)
        materialize_retention_curve(self.team, ALL_EVENTS_KIND)

        pv = self._curve_rows(PAGEVIEW_KIND)
        allev = self._curve_rows(ALL_EVENTS_KIND)

        self.assertEqual(len(pv), 1)
        self.assertEqual(list(pv[0][2]), [0])
        self.assertEqual(len(allev), 2)
        self.assertEqual(sorted(list(r[2]) for r in allev), [[0], [0, 2]])

    def test_offsets_capped_at_horizon(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp=_ts(2020, 1, 1))
        beyond = (datetime(2020, 1, 1, 5, tzinfo=UTC) + timedelta(days=HORIZON_DAYS + 5)).isoformat()
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp=beyond)
        flush_persons_and_events()

        materialize_retention_curve(self.team, PAGEVIEW_KIND)

        rows = self._curve_rows(PAGEVIEW_KIND)
        self.assertEqual(list(rows[0][2]), [0])

    def test_ensure_returns_ready_and_is_fresh_on_second_call(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp=_ts(2023, 9, 1))
        flush_persons_and_events()

        first = ensure_retention_curve(self.team, PAGEVIEW_KIND)
        self.assertTrue(first.ready)
        # Second call sees fresh data and returns ready without erroring.
        second = ensure_retention_curve(self.team, PAGEVIEW_KIND)
        self.assertTrue(second.ready)

    def test_ensure_rejects_unsupported_kind(self):
        self.assertFalse(ensure_retention_curve(self.team, "custom").ready)
