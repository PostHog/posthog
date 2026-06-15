from datetime import datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner

A = "00000000-0000-0000-0000-0000000000a1"
B = "00000000-0000-0000-0000-0000000000b2"
C = "00000000-0000-0000-0000-0000000000c3"


class TestRetentionActorReadParity(ClickhouseTestMixin, APIBaseTest):
    """The pre-agg read path must produce byte-identical results to the raw-events path for the
    gated-in shapes. Each case runs the same query with the modifier off (raw) and on (pre-agg)
    and asserts the count matrices match."""

    def setUp(self):
        super().setUp()
        self._created: set[str] = set()

    def _event(self, uid: str, day: int, event: str = "$pageview", hour: int = 8) -> None:
        if uid not in self._created:
            _create_person(team=self.team, distinct_ids=[uid], uuid=uid)
            self._created.add(uid)
        ts = datetime(2024, 1, 1 + day, hour, 0).strftime("%Y-%m-%d %H:%M:%S")
        _create_event(team=self.team, event=event, distinct_id=uid, timestamp=ts, person_id=uid)

    def _counts(self, query: dict, preagg: bool) -> list[list[int]]:
        runner = RetentionQueryRunner(
            team=self.team, query=query, modifiers=HogQLQueryModifiers(useRetentionPreAggregation=preagg)
        )
        results = runner.calculate().model_dump()["results"]
        return [[v["count"] for v in row["values"]] for row in results]

    def _seed(self) -> None:
        for uid, days in ((A, [0, 1, 3]), (B, [1, 2]), (C, [0, 5])):
            for d in days:
                self._event(uid, d)
        flush_persons_and_events()

    def _assert_parity(self, query: dict) -> None:
        raw = self._counts(query, preagg=False)
        pre = self._counts(query, preagg=True)
        self.assertEqual(raw, pre)
        # Guard against the degenerate all-zero matrix passing trivially.
        self.assertTrue(any(any(c for c in row) for row in raw), "expected some non-zero retention counts")

    def test_parity_first_time_day(self):
        self._seed()
        self._assert_parity(
            {
                "dateRange": {"date_from": "2024-01-01", "date_to": "2024-01-08"},
                "retentionFilter": {"period": "Day", "totalIntervals": 7, "retentionType": "retention_first_time"},
            }
        )

    def test_parity_first_ever_day(self):
        self._seed()
        self._assert_parity(
            {
                "dateRange": {"date_from": "2024-01-01", "date_to": "2024-01-08"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": "retention_first_ever_occurrence",
                },
            }
        )

    def test_parity_first_time_week(self):
        # Cohorts and returns spanning multiple weeks.
        for uid, days in ((A, [0, 1, 8, 15]), (B, [2, 9]), (C, [0, 16])):
            for d in days:
                self._event(uid, d)
        flush_persons_and_events()
        self._assert_parity(
            {
                "dateRange": {"date_from": "2024-01-01", "date_to": "2024-02-05"},
                "retentionFilter": {"period": "Week", "totalIntervals": 5, "retentionType": "retention_first_time"},
            }
        )

    @parameterized.expand(
        [
            # Near-midnight team-local events whose stored UTC instant lands on a different
            # calendar day — so a path that bucketed in UTC instead of team tz would diverge.
            ("america_new_york_late", "America/New_York", 23),
            ("asia_kolkata_early", "Asia/Kolkata", 2),
        ]
    )
    def test_parity_non_utc_team(self, _name: str, timezone: str, hour: int) -> None:
        self.team.timezone = timezone
        self.team.save()
        for uid, days in ((A, [0, 1, 3]), (B, [1, 2]), (C, [0, 5])):
            for d in days:
                self._event(uid, d, hour=hour)
        flush_persons_and_events()
        self._assert_parity(
            {
                "dateRange": {"date_from": "2024-01-01", "date_to": "2024-01-08"},
                "retentionFilter": {"period": "Day", "totalIntervals": 7, "retentionType": "retention_first_time"},
            }
        )

    def _gate(self, *, query_overrides: dict | None = None, retention_overrides: dict | None = None) -> bool:
        query = {
            "dateRange": {"date_from": "2024-01-01", "date_to": "2024-01-08"},
            "retentionFilter": {
                "period": "Day",
                "totalIntervals": 7,
                "retentionType": "retention_first_time",
                **(retention_overrides or {}),
            },
            **(query_overrides or {}),
        }
        runner = RetentionQueryRunner(
            team=self.team, query=query, modifiers=HogQLQueryModifiers(useRetentionPreAggregation=True)
        )
        return runner.should_use_retention_preagg

    def test_gate_on_for_covered_shape(self):
        # Anchor: the plain covered shape (modifier on) does take the pre-agg path, so the
        # fallback assertions below aren't passing vacuously.
        self.assertTrue(self._gate())

    @parameterized.expand(
        [
            ("breakdown", {"breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event"}}, {}),
            ("group_aggregation", {"aggregation_group_type_index": 0}, {}),
            ("test_accounts", {"filterTestAccounts": True}, {}),
            ("property_filter", {"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]}, {}),
            ("min_occurrences", {}, {"minimumOccurrences": 2}),
            ("24h_window", {}, {"timeWindowMode": "24_hour_windows"}),
            ("custom_bracket", {}, {"retentionCustomBrackets": [7, 2]}),
        ]
    )
    def test_gate_falls_back_for_unsupported_shapes(
        self, _name: str, query_overrides: dict, retention_overrides: dict
    ) -> None:
        # Each shape the pre-agg can't reproduce must fall through to raw, not slip past the gate
        # and crash on the read path.
        self.assertFalse(self._gate(query_overrides=query_overrides, retention_overrides=retention_overrides))

    def test_gate_off_uses_raw(self):
        # With the modifier off, the pre-agg path must not be taken — results still correct.
        self._seed()
        runner = RetentionQueryRunner(
            team=self.team,
            query={
                "dateRange": {"date_from": "2024-01-01", "date_to": "2024-01-08"},
                "retentionFilter": {"period": "Day", "totalIntervals": 7, "retentionType": "retention_first_time"},
            },
            modifiers=HogQLQueryModifiers(useRetentionPreAggregation=False),
        )
        self.assertFalse(runner.should_use_retention_preagg)
