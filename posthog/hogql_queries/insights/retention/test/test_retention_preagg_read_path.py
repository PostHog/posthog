from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, RetentionQuery

from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner

PAGEVIEW = {"id": "$pageview", "type": "events"}
ALL_EVENTS = {"id": None, "name": "All events", "type": "events"}


def _ts(day: int, hour: int = 5) -> str:
    return datetime(2023, 9, day, hour, tzinfo=UTC).isoformat()


class TestRetentionPreaggReadPath(ClickhouseTestMixin, APIBaseTest):
    def _seed(self):
        # All first-events are inside the window, so first-occurrence cohorting matches raw.
        for distinct_id, pageview_days, other_days in [
            ("p1", [3, 4, 6], [3]),
            ("p2", [3], [5]),
            ("p3", [4, 5], []),
            ("p4", [], [3, 4]),  # never a pageview — only in all-events
        ]:
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            for d in pageview_days:
                _create_event(team=self.team, event="$pageview", distinct_id=distinct_id, timestamp=_ts(d))
            for d in other_days:
                _create_event(team=self.team, event="custom", distinct_id=distinct_id, timestamp=_ts(d))
        flush_persons_and_events()

    def _run(self, *, entity, retention_type, use_preagg):
        query = {
            "kind": "RetentionQuery",
            "dateRange": {"date_from": _ts(3, 0), "date_to": _ts(9, 0)},
            "retentionFilter": {
                "period": "Day",
                "totalIntervals": 7,
                "retentionType": retention_type,
                "targetEntity": entity,
                "returningEntity": entity,
            },
        }
        return RetentionQueryRunner(
            team=self.team,
            query=RetentionQuery(**query),
            modifiers=HogQLQueryModifiers(useRetentionPreAggregation=use_preagg),
        )

    @staticmethod
    def _counts(results):
        return [[v["count"] for v in row["values"]] for row in results]

    @parameterized.expand(
        [
            ("first_time_pageview", "retention_first_time", PAGEVIEW),
            ("first_time_all_events", "retention_first_time", ALL_EVENTS),
            ("first_ever_pageview", "retention_first_ever_occurrence", PAGEVIEW),
            ("first_ever_all_events", "retention_first_ever_occurrence", ALL_EVENTS),
        ]
    )
    def test_preagg_matches_raw_events(self, _name, retention_type, entity):
        self._seed()
        raw = (
            self._run(entity=entity, retention_type=retention_type, use_preagg=False)
            .calculate()
            .model_dump()["results"]
        )
        preagg_runner = self._run(entity=entity, retention_type=retention_type, use_preagg=True)
        self.assertTrue(preagg_runner.should_use_retention_preagg)
        preagg = preagg_runner.calculate().model_dump()["results"]

        self.assertEqual(self._counts(raw), self._counts(preagg))
        # Sanity: there is some retention to compare (not an all-zero matrix).
        self.assertGreater(sum(sum(v["count"] for v in row["values"]) for row in raw), 0)

    def test_actor_with_pre_window_history_excluded(self):
        # The case the per-day grain gets wrong: p_old's first pageview predates the window but
        # they're active inside it. First-occurrence retention must NOT cohort them in-window.
        self._seed()
        _create_person(team_id=self.team.pk, distinct_ids=["p_old"])
        _create_event(team=self.team, event="$pageview", distinct_id="p_old", timestamp=_ts(1))  # before date_from
        _create_event(team=self.team, event="$pageview", distinct_id="p_old", timestamp=_ts(4))  # inside window
        flush_persons_and_events()

        raw = (
            self._run(entity=PAGEVIEW, retention_type="retention_first_time", use_preagg=False)
            .calculate()
            .model_dump()["results"]
        )
        preagg_runner = self._run(entity=PAGEVIEW, retention_type="retention_first_time", use_preagg=True)
        self.assertTrue(preagg_runner.should_use_retention_preagg)
        preagg = preagg_runner.calculate().model_dump()["results"]
        self.assertEqual(self._counts(raw), self._counts(preagg))

    def test_gate(self):
        self._seed()
        # recurring → raw events
        self.assertFalse(
            self._run(
                entity=PAGEVIEW, retention_type="retention_recurring", use_preagg=True
            ).should_use_retention_preagg
        )
        # first_ever → allowed
        self.assertTrue(
            self._run(
                entity=PAGEVIEW, retention_type="retention_first_ever_occurrence", use_preagg=True
            ).should_use_retention_preagg
        )
        # custom event → raw events
        self.assertFalse(
            self._run(
                entity={"id": "custom", "type": "events"}, retention_type="retention_first_time", use_preagg=True
            ).should_use_retention_preagg
        )
        # modifier off → raw events
        self.assertFalse(
            self._run(
                entity=PAGEVIEW, retention_type="retention_first_time", use_preagg=False
            ).should_use_retention_preagg
        )
