from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, RetentionQuery

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob


@override_settings(IN_UNIT_TESTING=True)
class TestRetentionPreAggRoutingGate(ClickhouseTestMixin, APIBaseTest):
    """Gate decides whether a query qualifies for the v1 pre-agg path. Each ineligible
    shape must short-circuit to False so we don't silently route an unsupported query
    through pre-agg."""

    def _runner(self, *, query_overrides=None, modifier_on=True) -> RetentionQueryRunner:
        base_query = {
            "dateRange": {"date_from": "-7d"},
            "retentionFilter": {
                "retentionType": "retention_recurring",
                "targetEntity": {"id": "$pageview", "type": "events"},
                "returningEntity": {"id": "$pageview", "type": "events"},
            },
        }
        if query_overrides:
            for key, value in query_overrides.items():
                if key in {"retentionFilter", "breakdownFilter"} and value is not None:
                    base_query.setdefault(key, {}).update(value)
                else:
                    base_query[key] = value
        modifiers = HogQLQueryModifiers(useRetentionPreAggregation=modifier_on or None)
        return RetentionQueryRunner(query=RetentionQuery(**base_query), team=self.team, modifiers=modifiers)

    def test_default_off_when_modifier_unset(self) -> None:
        # Without the modifier, gate stays False regardless of query shape.
        assert self._runner(modifier_on=False).should_use_retention_preagg is False

    def test_eligible_recurring_same_entity(self) -> None:
        # Canonical v1 happy-path shape — recurring, same entity, person retention.
        assert self._runner().should_use_retention_preagg is True

    def test_eligible_first_time_different_entity(self) -> None:
        # Different start / return entities are fine — pre-agg captures all events.
        assert (
            self._runner(
                query_overrides={
                    "retentionFilter": {
                        "retentionType": "retention_first_time",
                        "targetEntity": {"id": "$screen", "type": "events"},
                        "returningEntity": {"id": "$pageview", "type": "events"},
                    },
                }
            ).should_use_retention_preagg
            is True
        )

    @parameterized.expand(
        [
            # First-ever needs lookback beyond the materialised window.
            ("first_ever", {"retentionFilter": {"retentionType": "retention_first_ever_occurrence"}}),
            # Property aggregation needs event property values the pre-agg doesn't store.
            (
                "property_aggregation",
                {
                    "retentionFilter": {
                        "aggregationType": "sum",
                        "aggregationProperty": "revenue",
                    }
                },
            ),
            # 24h windows have a different per-interval shape the v1 builder doesn't reproduce.
            ("24h_windows", {"retentionFilter": {"timeWindowMode": "24_hour_windows"}}),
            # Entity property filter — pre-agg can't filter by event property.
            (
                "entity_property_filter",
                {
                    "retentionFilter": {
                        "targetEntity": {
                            "id": "$pageview",
                            "type": "events",
                            "properties": [{"key": "country", "value": "US", "type": "event"}],
                        }
                    }
                },
            ),
            # Query-level event property filter — same reason.
            (
                "query_property_filter",
                {"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]},
            ),
        ]
    )
    def test_gate_rejects(self, _name: str, query_overrides: dict) -> None:
        assert self._runner(query_overrides=query_overrides).should_use_retention_preagg is False


@override_settings(IN_UNIT_TESTING=True)
class TestRetentionPreAggCorrectness(ClickhouseTestMixin, APIBaseTest):
    """Run the same query through both paths and assert identical retention output.
    Without correctness here, the routing gate would silently serve wrong results."""

    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        # See test_retention_lazy_precompute setUp — without stopping TTL merges,
        # precompute rows can drop before the read.
        sync_execute("SYSTEM STOP TTL MERGES sharded_retention_actor_event_day")

    def _seed_basic_retention(self) -> None:
        # Three actors, three days. p1: active 2026-01-01 and 2026-01-02 ($pageview both).
        # p2: active 2026-01-01 only. p3: active 2026-01-02 only. Standard small retention shape.
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={})
        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={})
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-01T09:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-01T15:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-02T11:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="p2", timestamp="2026-01-01T12:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="p3", timestamp="2026-01-02T10:00:00Z")
        flush_persons_and_events()

    def _run_retention(self, *, use_preagg: bool):
        query = RetentionQuery(
            dateRange={"date_from": "2026-01-01T00:00:00Z", "date_to": "2026-01-04T00:00:00Z"},
            retentionFilter={
                "retentionType": "retention_recurring",
                "period": "Day",
                "totalIntervals": 3,
                "targetEntity": {"id": "$pageview", "type": "events"},
                "returningEntity": {"id": "$pageview", "type": "events"},
            },
        )
        modifiers = HogQLQueryModifiers(useRetentionPreAggregation=use_preagg or None)
        runner = RetentionQueryRunner(query=query, team=self.team, modifiers=modifiers)
        return runner.calculate()

    def test_pre_agg_matches_raw_events_recurring_same_entity(self) -> None:
        self._seed_basic_retention()
        raw = self._run_retention(use_preagg=False)
        preagg = self._run_retention(use_preagg=True)

        # Same retention buckets, same counts. Comparing the result struct directly is
        # the strongest possible correctness check — if the pre-agg path produced any
        # divergence we'd see it here.
        assert len(raw.results) == len(preagg.results)
        for raw_row, preagg_row in zip(raw.results, preagg.results):
            assert raw_row.date == preagg_row.date
            assert len(raw_row.values) == len(preagg_row.values)
            for raw_bucket, preagg_bucket in zip(raw_row.values, preagg_row.values):
                assert raw_bucket.count == preagg_bucket.count, (
                    f"Bucket count mismatch at date {raw_row.date}: raw={raw_bucket.count} preagg={preagg_bucket.count}"
                )

    def test_pre_agg_matches_raw_events_first_time_same_entity(self) -> None:
        self._seed_basic_retention()
        query_kwargs = {
            "dateRange": {"date_from": "2026-01-01T00:00:00Z", "date_to": "2026-01-04T00:00:00Z"},
            "retentionFilter": {
                "retentionType": "retention_first_time",
                "period": "Day",
                "totalIntervals": 3,
                "targetEntity": {"id": "$pageview", "type": "events"},
                "returningEntity": {"id": "$pageview", "type": "events"},
            },
        }

        raw_runner = RetentionQueryRunner(
            query=RetentionQuery(**query_kwargs),
            team=self.team,
            modifiers=HogQLQueryModifiers(useRetentionPreAggregation=None),
        )
        preagg_runner = RetentionQueryRunner(
            query=RetentionQuery(**query_kwargs),
            team=self.team,
            modifiers=HogQLQueryModifiers(useRetentionPreAggregation=True),
        )

        raw = raw_runner.calculate()
        preagg = preagg_runner.calculate()

        assert len(raw.results) == len(preagg.results)
        for raw_row, preagg_row in zip(raw.results, preagg.results):
            assert raw_row.date == preagg_row.date
            for raw_bucket, preagg_bucket in zip(raw_row.values, preagg_row.values):
                assert raw_bucket.count == preagg_bucket.count

    def test_falls_through_to_raw_when_materialisation_returns_no_jobs(self) -> None:
        # When the gate is satisfied but the time range somehow can't be materialised
        # (no events in the window), ensure the query still returns — falling through
        # to raw events rather than crashing.
        # No events seeded here. The query window has nothing to materialise.
        result = self._run_retention(use_preagg=True)
        # Empty results are fine — the important thing is the query ran without error.
        assert result.results is not None
