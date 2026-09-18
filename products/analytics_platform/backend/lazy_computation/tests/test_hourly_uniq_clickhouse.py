from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest, _create_event, flush_persons_and_events
from unittest.mock import patch

from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.hourly_uniq_sql import HOURLY_UNIQ_TABLE_SQL, SHARDED_HOURLY_UNIQ_TABLE_SQL
from posthog.models import PropertyDefinition

from products.analytics_platform.backend.lazy_computation.hourly_uniq import plan_hourly_uniq
from products.analytics_platform.backend.lazy_computation.hourly_uniq_cache import (
    HourlyUniqFreshness,
    read_hourly_uniq,
    warm_hourly_uniq,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob


class TestHourlyUniqClickHouse(BaseTest):
    def test_reuses_history_without_read_side_builds_and_invalidates_revision(self):
        sync_execute(SHARDED_HOURLY_UNIQ_TABLE_SQL())
        sync_execute(HOURLY_UNIQ_TABLE_SQL())
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        self.team.timezone = "UTC"
        self.team.save()
        PropertyDefinition.objects.create(
            team=self.team, name="eligible", type=PropertyDefinition.Type.EVENT, property_type="Boolean"
        )
        # Fresh synthetic events exercise a missing hour, zero conditional values,
        # repeated persons, overlapping predicates, and historical/live buckets.
        for hours in [1, 2, 25, 73, 90]:
            for _ in range(4):
                person_id = uuid4()
                for event in ["sample", "sample", "other"]:
                    _create_event(
                        team=self.team,
                        event=event,
                        distinct_id=str(person_id),
                        person_id=person_id,
                        timestamp=now - timedelta(hours=hours),
                        properties={"category": "demo", "eligible": True},
                    )
        _create_event(
            team=self.team,
            event="neither",
            distinct_id="empty-conditions",
            person_id=uuid4(),
            timestamp=now - timedelta(hours=7),
            properties={"category": "demo", "eligible": True},
        )
        flush_persons_and_events()
        sql = """SELECT toStartOfHour(timestamp) AS bucket,
        uniqIf(person_id, event = 'sample' AND properties.eligible = true) + 2 * uniqIf(person_id, event = 'other') AS weighted
        FROM events WHERE timestamp >= toStartOfHour(now()) - INTERVAL 120 HOUR
        AND timestamp < toStartOfHour(now()) AND properties.category = 'demo'
        GROUP BY bucket ORDER BY bucket"""
        plan = plan_hourly_uniq(sql, now=now, timezone="UTC")
        assert plan is not None
        policy = HourlyUniqFreshness(historical_ttl_seconds=3600, live_hours=24, revision="one")
        jobs_before = PreaggregationJob.objects.filter(team=self.team).count()
        assert read_hourly_uniq(self.team, plan, policy) is None
        assert PreaggregationJob.objects.filter(team=self.team).count() == jobs_before
        result = warm_hourly_uniq(self.team, plan, policy)
        assert result is not None and result.ready, result
        assert all(
            job.time_range_end - job.time_range_start <= timedelta(days=1)
            for job in PreaggregationJob.objects.filter(team=self.team)
        )
        query = read_hourly_uniq(self.team, plan, policy)
        assert query is not None
        expected = execute_hogql_query(
            plan.reference_query(), team=self.team, limit_context=LimitContext.SAVED_QUERY
        ).results
        actual = execute_hogql_query(query, team=self.team, limit_context=LimitContext.SAVED_QUERY).results
        assert actual == expected
        assert len(actual) == 6
        assert [row[1] for row in actual].count(0) == 1
        jobs_after = PreaggregationJob.objects.filter(team=self.team).count()
        with patch(
            "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.create_lazy_computation_job",
            side_effect=AssertionError("read must never build"),
        ):
            assert read_hourly_uniq(self.team, plan, policy) is not None
        assert PreaggregationJob.objects.filter(team=self.team).count() == jobs_after
        assert (
            read_hourly_uniq(
                self.team, plan, HourlyUniqFreshness(historical_ttl_seconds=3600, live_hours=24, revision="two")
            )
            is None
        )

        # A late historical event is deliberately not hidden behind a claim of
        # exact freshness: revision invalidation is required and restores parity.
        late_person = uuid4()
        _create_event(
            team=self.team,
            event="sample",
            distinct_id=str(late_person),
            person_id=late_person,
            timestamp=now - timedelta(hours=73),
            properties={"category": "demo", "eligible": True},
        )
        flush_persons_and_events()
        changed = execute_hogql_query(
            plan.reference_query(), team=self.team, limit_context=LimitContext.SAVED_QUERY
        ).results
        assert changed != actual
        refreshed_policy = HourlyUniqFreshness(historical_ttl_seconds=3600, live_hours=24, revision="two")
        rebuilt = warm_hourly_uniq(self.team, plan, refreshed_policy)
        assert rebuilt is not None and rebuilt.ready
        refreshed_query = read_hourly_uniq(self.team, plan, refreshed_policy)
        assert refreshed_query is not None
        assert (
            execute_hogql_query(refreshed_query, team=self.team, limit_context=LimitContext.SAVED_QUERY).results
            == changed
        )

        # A persisted DateTime64 bucket must retain the original toStartOfHour
        # output type when an outer projection formats it as a string.
        projected = plan_hourly_uniq(
            f"SELECT bucket, toString(bucket) AS label, weighted FROM ({sql}) ORDER BY bucket", now=now, timezone="UTC"
        )
        assert projected is not None
        projected_query = read_hourly_uniq(self.team, projected, refreshed_policy)
        assert projected_query is not None
        expected_labels = execute_hogql_query(
            projected.reference_query(), team=self.team, limit_context=LimitContext.SAVED_QUERY
        ).results
        assert (
            execute_hogql_query(projected_query, team=self.team, limit_context=LimitContext.SAVED_QUERY).results
            == expected_labels
        )

    def test_age_based_refresh_repairs_late_events_without_rebuilding_old_days(self):
        sync_execute(SHARDED_HOURLY_UNIQ_TABLE_SQL())
        sync_execute(HOURLY_UNIQ_TABLE_SQL())
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        self.team.timezone = "UTC"
        self.team.save()
        sql = """SELECT toStartOfHour(timestamp) AS bucket, uniq(person_id) AS visitors
        FROM events WHERE timestamp >= toStartOfHour(now()) - INTERVAL 240 HOUR
        AND timestamp < toStartOfHour(now()) GROUP BY bucket ORDER BY bucket"""

        def event(hours):
            person = uuid4()
            _create_event(
                team=self.team,
                event="sample",
                distinct_id=str(person),
                person_id=person,
                timestamp=now - timedelta(hours=hours),
            )

        event(30)
        event(190)
        flush_persons_and_events()
        plan = plan_hourly_uniq(sql, now=now, timezone="UTC")
        assert plan is not None
        policy = HourlyUniqFreshness.age_based(revision="synthetic")
        built = warm_hourly_uniq(self.team, plan, policy)
        assert built is not None and built.ready
        jobs = PreaggregationJob.objects.filter(team=self.team)
        old_ids = set(jobs.filter(time_range_end__lte=now - timedelta(days=5)).values_list("id", flat=True))
        assert old_ids
        first = read_hourly_uniq(self.team, plan, policy)
        assert first is not None
        before = execute_hogql_query(first, team=self.team, limit_context=LimitContext.SAVED_QUERY).results
        event(30)
        flush_persons_and_events()
        # Simulate cached jobs passing the recent band's one-hour refresh age.
        # Older jobs remain within their longer TTL and must be reused.
        jobs.update(created_at=now - timedelta(hours=2))
        assert read_hourly_uniq(self.team, plan, policy) is None
        refreshed = warm_hourly_uniq(self.team, plan, policy)
        assert refreshed is not None and refreshed.ready
        assert old_ids.issubset(set(refreshed.job_ids))
        query = read_hourly_uniq(self.team, plan, policy)
        assert query is not None
        after = execute_hogql_query(query, team=self.team, limit_context=LimitContext.SAVED_QUERY).results
        expected = execute_hogql_query(
            plan.reference_query(), team=self.team, limit_context=LimitContext.SAVED_QUERY
        ).results
        assert after == expected
        assert after != before

        event(0)
        flush_persons_and_events()
        next_midnight = (now + timedelta(days=1)).replace(hour=0)
        advanced = plan_hourly_uniq(sql, now=next_midnight, timezone="UTC")
        assert advanced is not None
        retained_old_ids = set(
            jobs.filter(id__in=old_ids, time_range_end__gt=advanced.start).values_list("id", flat=True)
        )
        assert retained_old_ids
        count_before_rollover = jobs.count()
        assert read_hourly_uniq(self.team, advanced, policy) is None
        assert jobs.count() == count_before_rollover
        rollover = warm_hourly_uniq(self.team, advanced, policy)
        assert rollover is not None and rollover.ready
        assert retained_old_ids.issubset(set(rollover.job_ids))
        advanced_query = read_hourly_uniq(self.team, advanced, policy)
        assert advanced_query is not None
        advanced_rows = execute_hogql_query(
            advanced_query, team=self.team, limit_context=LimitContext.SAVED_QUERY
        ).results
        assert (
            advanced_rows
            == execute_hogql_query(
                advanced.reference_query(), team=self.team, limit_context=LimitContext.SAVED_QUERY
            ).results
        )
        assert len(advanced_rows) == len(after) + 1
