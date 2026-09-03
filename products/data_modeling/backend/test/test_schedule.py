import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized
from temporalio.client import ScheduleCalendarSpec, ScheduleListActionStartWorkflow

from products.data_modeling.backend.models import Node
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.schedule import (
    _deterministic_int,
    build_schedule_spec,
    get_v2_saved_query_ids,
    get_v2_scheduled_dag_ids,
    partition_saved_queries_by_v2_schedule,
)


class TestDeterministicInt:
    def test_same_inputs_produce_same_output(self):
        entity_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert _deterministic_int(entity_id, "salt") == _deterministic_int(entity_id, "salt")

    def test_different_salts_produce_different_outputs(self):
        entity_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert _deterministic_int(entity_id, "a") != _deterministic_int(entity_id, "b")

    def test_different_ids_produce_different_outputs(self):
        id_a = uuid.UUID("12345678-1234-5678-1234-567812345678")
        id_b = uuid.UUID("87654321-4321-8765-4321-876543218765")
        assert _deterministic_int(id_a, "salt") != _deterministic_int(id_b, "salt")


class TestShortIntervalSpec:
    def test_15min_uses_calendar_spec_with_4_minutes(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(minutes=15))
        assert len(spec.calendars) == 1
        assert len(spec.calendars[0].minute) == 4

    def test_30min_uses_calendar_spec_with_2_minutes(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(minutes=30))
        assert len(spec.calendars[0].minute) == 2

    def test_1hr_uses_calendar_spec_with_1_minute(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=1))
        assert len(spec.calendars[0].minute) == 1

    def test_15min_runs_every_hour(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(minutes=15))
        assert len(spec.calendars[0].hour) == 1
        assert spec.calendars[0].hour[0].start == 0
        assert spec.calendars[0].hour[0].end == 23

    def test_15min_minutes_are_spaced_15_apart(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(minutes=15))
        mins = sorted(r.start for r in spec.calendars[0].minute)
        for i in range(1, len(mins)):
            assert mins[i] - mins[i - 1] == 15

    def test_jitter_is_1_minute(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(minutes=15))
        assert spec.jitter == timedelta(minutes=1)

    def test_deterministic_same_id(self):
        entity_id = uuid.uuid4()
        spec_a = build_schedule_spec(entity_id, timedelta(minutes=30))
        spec_b = build_schedule_spec(entity_id, timedelta(minutes=30))
        assert spec_a.calendars[0].minute == spec_b.calendars[0].minute

    def test_timezone_set(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(minutes=15), team_timezone="US/Eastern")
        assert spec.time_zone_name == "US/Eastern"

    def test_distribution_15min_covers_all_buckets(self):
        base_mins: Counter[int] = Counter()
        for i in range(1000):
            entity_id = uuid.UUID(int=i)
            spec = build_schedule_spec(entity_id, timedelta(minutes=15))
            base_mins[min(r.start for r in spec.calendars[0].minute)] += 1
        assert len(base_mins) == 15

    def test_distribution_60min_covers_all_buckets(self):
        base_mins: Counter[int] = Counter()
        for i in range(1000):
            entity_id = uuid.UUID(int=i)
            spec = build_schedule_spec(entity_id, timedelta(minutes=60))
            base_mins[min(r.start for r in spec.calendars[0].minute)] += 1
        assert len(base_mins) == 60


class TestMediumIntervalSpec:
    def test_6hr_uses_calendar_spec_with_4_hours(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=6), team_timezone="US/Eastern")
        assert len(spec.calendars) == 1
        calendar: ScheduleCalendarSpec = spec.calendars[0]
        assert len(calendar.hour) == 4
        assert spec.time_zone_name == "US/Eastern"

    def test_12hr_uses_calendar_spec_with_2_hours(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=12))
        calendar: ScheduleCalendarSpec = spec.calendars[0]
        assert len(calendar.hour) == 2

    def test_24hr_uses_calendar_spec_with_1_hour(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=24))
        calendar: ScheduleCalendarSpec = spec.calendars[0]
        assert len(calendar.hour) == 1

    def test_6hr_hours_are_spaced_6_apart(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=6))
        hours = sorted(r.start for r in spec.calendars[0].hour)
        for i in range(1, len(hours)):
            assert hours[i] - hours[i - 1] == 6

    def test_12hr_hours_are_spaced_12_apart(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=12))
        hours = sorted(r.start for r in spec.calendars[0].hour)
        assert hours[1] - hours[0] == 12

    def test_jitter_is_1_hour(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=6))
        assert spec.jitter == timedelta(hours=1)

    def test_deterministic_same_id(self):
        entity_id = uuid.uuid4()
        spec_a = build_schedule_spec(entity_id, timedelta(hours=24))
        spec_b = build_schedule_spec(entity_id, timedelta(hours=24))
        assert spec_a.calendars[0].hour[0].start == spec_b.calendars[0].hour[0].start

    def test_distribution_24hr_covers_all_hours(self):
        hours: Counter[int] = Counter()
        for i in range(1000):
            entity_id = uuid.UUID(int=i)
            spec = build_schedule_spec(entity_id, timedelta(hours=24))
            hours[spec.calendars[0].hour[0].start] += 1
        assert len(hours) == 24

    def test_distribution_6hr_covers_all_buckets(self):
        base_hours: Counter[int] = Counter()
        for i in range(1000):
            entity_id = uuid.UUID(int=i)
            spec = build_schedule_spec(entity_id, timedelta(hours=6))
            base_hours[min(r.start for r in spec.calendars[0].hour)] += 1
        assert len(base_hours) == 6


class TestWeeklySpec:
    def test_uses_calendar_spec_with_day_and_hour(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(days=7), team_timezone="Europe/London")
        assert len(spec.calendars) == 1
        calendar: ScheduleCalendarSpec = spec.calendars[0]
        assert len(calendar.day_of_week) == 1
        assert len(calendar.hour) == 1
        assert spec.time_zone_name == "Europe/London"

    def test_jitter_is_1_hour(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(days=7))
        assert spec.jitter == timedelta(hours=1)

    def test_deterministic_same_id(self):
        entity_id = uuid.uuid4()
        spec_a = build_schedule_spec(entity_id, timedelta(days=7))
        spec_b = build_schedule_spec(entity_id, timedelta(days=7))
        assert spec_a.calendars[0].day_of_week[0].start == spec_b.calendars[0].day_of_week[0].start
        assert spec_a.calendars[0].hour[0].start == spec_b.calendars[0].hour[0].start

    def test_distribution_covers_all_days(self):
        days: Counter[int] = Counter()
        for i in range(1000):
            entity_id = uuid.UUID(int=i)
            spec = build_schedule_spec(entity_id, timedelta(days=7))
            days[spec.calendars[0].day_of_week[0].start] += 1
        assert len(days) == 7

    def test_distribution_covers_all_hours(self):
        hours: Counter[int] = Counter()
        for i in range(1000):
            entity_id = uuid.UUID(int=i)
            spec = build_schedule_spec(entity_id, timedelta(days=7))
            hours[spec.calendars[0].hour[0].start] += 1
        assert len(hours) == 24


class TestMonthlySpec:
    def test_uses_calendar_spec_with_day_and_hour(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(days=30), team_timezone="Asia/Tokyo")
        assert len(spec.calendars) == 1
        calendar: ScheduleCalendarSpec = spec.calendars[0]
        assert len(calendar.day_of_month) == 1
        assert len(calendar.hour) == 1
        assert spec.time_zone_name == "Asia/Tokyo"

    def test_jitter_is_1_hour(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(days=30))
        assert spec.jitter == timedelta(hours=1)

    def test_day_of_month_in_safe_range(self):
        for i in range(500):
            entity_id = uuid.UUID(int=i)
            spec = build_schedule_spec(entity_id, timedelta(days=30))
            day = spec.calendars[0].day_of_month[0].start
            assert 1 <= day <= 28

    def test_deterministic_same_id(self):
        entity_id = uuid.uuid4()
        spec_a = build_schedule_spec(entity_id, timedelta(days=30))
        spec_b = build_schedule_spec(entity_id, timedelta(days=30))
        assert spec_a.calendars[0].day_of_month[0].start == spec_b.calendars[0].day_of_month[0].start

    def test_distribution_covers_all_28_days(self):
        days: Counter[int] = Counter()
        for i in range(5000):
            entity_id = uuid.UUID(int=i)
            spec = build_schedule_spec(entity_id, timedelta(days=30))
            days[spec.calendars[0].day_of_month[0].start] += 1
        assert len(days) == 28


class TestTierPhaseAlignment:
    """Cadence tiers of one DAG must not be phase-aligned.

    All tiers of a DAG derive their bucket from the same entity_id, so unless the
    interval participates in the salt, a coarser tier's fire times are a subset of
    every finer tier's — every tier of a DAG piles onto the same minute/hour.
    """

    N = 500

    @staticmethod
    def _minute_set(spec) -> set[int]:
        return {r.start for r in spec.calendars[0].minute}

    @staticmethod
    def _hour_set(spec) -> set[int]:
        return {r.start for r in spec.calendars[0].hour}

    @parameterized.expand(
        [
            ("15min_vs_30min", timedelta(minutes=15), timedelta(minutes=30), "_minute_set"),
            ("15min_vs_1hr", timedelta(minutes=15), timedelta(hours=1), "_minute_set"),
            ("30min_vs_1hr", timedelta(minutes=30), timedelta(hours=1), "_minute_set"),
            ("6hr_vs_12hr", timedelta(hours=6), timedelta(hours=12), "_hour_set"),
            ("6hr_vs_24hr", timedelta(hours=6), timedelta(hours=24), "_hour_set"),
            ("12hr_vs_24hr", timedelta(hours=12), timedelta(hours=24), "_hour_set"),
            ("24hr_vs_weekly", timedelta(hours=24), timedelta(days=7), "_hour_set"),
        ]
    )
    def test_coarser_tier_not_contained_in_finer(self, _name, finer, coarser, extractor):
        buckets = getattr(self, extractor)
        aligned = 0
        for i in range(self.N):
            entity_id = uuid.UUID(int=i)
            finer_set = buckets(build_schedule_spec(entity_id, finer))
            coarser_set = buckets(build_schedule_spec(entity_id, coarser))
            if coarser_set <= finer_set:
                aligned += 1
        # Incidental overlap is fine (expected ~1/interval-ratio of ids); systematic
        # alignment is the defect.
        assert aligned < self.N // 2, f"{aligned}/{self.N} ids have the coarser tier phase-aligned into the finer"


class TestBuildScheduleSpecEdgeCases:
    def test_timezone_passed_to_all_tiers(self):
        for interval in [timedelta(minutes=15), timedelta(hours=6), timedelta(days=7), timedelta(days=30)]:
            spec = build_schedule_spec(uuid.uuid4(), interval, team_timezone="America/New_York")
            assert spec.time_zone_name == "America/New_York"

    def test_boundary_1hr_is_short(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=1))
        assert len(spec.calendars) == 1
        # Short tier: minute-level buckets, 1 window for 60min interval
        assert len(spec.calendars[0].minute) == 1

    def test_boundary_6hr_is_medium(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=6))
        assert len(spec.calendars) == 1
        assert len(spec.calendars[0].hour) == 4

    def test_boundary_24hr_is_medium(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(hours=24))
        assert len(spec.calendars) == 1
        assert len(spec.calendars[0].hour) == 1

    def test_boundary_7d_is_weekly(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(days=7))
        assert len(spec.calendars[0].day_of_week) == 1

    def test_boundary_30d_is_monthly(self):
        spec = build_schedule_spec(uuid.uuid4(), timedelta(days=30))
        assert len(spec.calendars[0].day_of_month) == 1


@pytest.mark.django_db
class TestV2ScheduleGuard(BaseTest):
    def _saved_query_on_dag(self, name: str, dag: DAG) -> DataWarehouseSavedQuery:
        sq = DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        Node.objects.create(team=self.team, dag=dag, saved_query=sq, type=NodeType.VIEW)
        return sq

    def setUp(self):
        super().setUp()
        self.v2_dag = DAG.objects.create(team=self.team, name="v2")
        self.v1_dag = DAG.objects.create(team=self.team, name="v1")
        self.sq_on_v2 = self._saved_query_on_dag("on_v2", self.v2_dag)
        self.sq_on_v1 = self._saved_query_on_dag("on_v1", self.v1_dag)

    def test_get_v2_saved_query_ids_returns_only_migrated_dag_queries(self):
        with mock.patch(
            "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids",
            return_value={str(self.v2_dag.id)},
        ):
            result = get_v2_saved_query_ids([self.sq_on_v2.id, self.sq_on_v1.id])
        assert result == {self.sq_on_v2.id}

    def test_get_v2_saved_query_ids_empty_when_no_v2_schedules(self):
        with mock.patch(
            "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids",
            return_value=set(),
        ):
            result = get_v2_saved_query_ids([self.sq_on_v2.id, self.sq_on_v1.id])
        assert result == set()

    def test_partition_splits_v1_eligible_from_v2(self):
        with mock.patch(
            "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids",
            return_value={str(self.v2_dag.id)},
        ):
            eligible, on_v2 = partition_saved_queries_by_v2_schedule([self.sq_on_v2, self.sq_on_v1])
        assert [sq.id for sq in eligible] == [self.sq_on_v1.id]
        assert [sq.id for sq in on_v2] == [self.sq_on_v2.id]

    def test_partition_keeps_all_when_no_v2_schedules(self):
        with mock.patch(
            "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids",
            return_value=set(),
        ):
            eligible, on_v2 = partition_saved_queries_by_v2_schedule([self.sq_on_v2, self.sq_on_v1])
        assert {sq.id for sq in eligible} == {self.sq_on_v2.id, self.sq_on_v1.id}
        assert on_v2 == []

    def test_partition_empty_input(self):
        eligible, on_v2 = partition_saved_queries_by_v2_schedule([])
        assert eligible == []
        assert on_v2 == []

    def _saved_query(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

    def test_saved_query_without_a_node_is_not_reported_as_v1_eligible(self):
        nodeless = self._saved_query("sync_failed")
        with mock.patch(
            "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids",
            return_value={str(self.v2_dag.id)},
        ):
            result = get_v2_saved_query_ids([nodeless.id], team_id=self.team.pk)
        assert result == {nodeless.id}

    def test_saved_query_without_a_node_stays_v1_eligible_when_no_dag_is_v2_scheduled(self):
        nodeless = self._saved_query("sync_failed_on_v1_team")
        with mock.patch(
            "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids",
            return_value=set(),
        ):
            result = get_v2_saved_query_ids([nodeless.id], team_id=self.team.pk)
        assert result == set()

    @parameterized.expand([("v2_node_created_first", True), ("v1_node_created_first", False)])
    def test_saved_query_in_two_dags_is_on_v2_when_either_dag_is(self, _name: str, v2_first: bool):
        shared = self._saved_query("in_two_dags")
        for dag in [self.v2_dag, self.v1_dag] if v2_first else [self.v1_dag, self.v2_dag]:
            Node.objects.create(team=self.team, dag=dag, saved_query=shared, type=NodeType.VIEW)
        with mock.patch(
            "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids",
            return_value={str(self.v2_dag.id)},
        ):
            result = get_v2_saved_query_ids([shared.id], team_id=self.team.pk)
        assert result == {shared.id}


class TestGetV2ScheduledDagIds:
    def _listing(self, schedule_id: str, workflow: str):
        action = mock.Mock(spec=ScheduleListActionStartWorkflow, workflow=workflow)
        return mock.Mock(id=schedule_id, schedule=mock.Mock(action=action))

    def test_full_sweep_scopes_by_schedule_type_server_side(self):
        captured: dict = {}
        listings = [
            self._listing("dag-on-v2", "data-modeling-execute-dag"),
            self._listing("sq-on-v1", "data-modeling-run"),
        ]

        async def fake_list_schedules(*args, **kwargs):
            captured["kwargs"] = kwargs

            async def gen():
                for listing in listings:
                    yield listing

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules
        with mock.patch(
            "products.data_modeling.backend.schedule.async_connect",
            new=mock.AsyncMock(return_value=temporal),
        ):
            result = get_v2_scheduled_dag_ids()

        # WorkflowType isn't queryable on schedules, so the full sweep scopes server-side on the
        # PostHogScheduleType tag instead of paginating the whole namespace.
        assert captured["kwargs"]["query"] == 'PostHogScheduleType = "data-modeling-execute-dag"'
        assert result == {"dag-on-v2"}

    def test_scopes_listing_by_posthog_dag_id_when_candidates_given(self):
        captured: dict = {}
        listings = [
            self._listing("dag-on-v2", "data-modeling-execute-dag"),
            self._listing("sq-on-v1", "data-modeling-run"),
        ]

        async def fake_list_schedules(*args, **kwargs):
            captured["kwargs"] = kwargs

            async def gen():
                for listing in listings:
                    yield listing

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules
        with mock.patch(
            "products.data_modeling.backend.schedule.async_connect",
            new=mock.AsyncMock(return_value=temporal),
        ):
            result = get_v2_scheduled_dag_ids({"dag-on-v2"})

        # Server-side filtering on the PostHogDagId search attribute (allowed, unlike WorkflowType)
        # keeps us from paginating the whole namespace.
        assert captured["kwargs"]["query"] == "PostHogDagId IN ('dag-on-v2')"
        assert result == {"dag-on-v2"}

    def test_tiered_schedule_ids_resolve_to_the_dag_id(self):
        # cadence-tier schedules are "{dag_id}:{seconds}" or "{dag_id}:{seconds}:{anchor}";
        # returning them raw (or mis-splitting the anchored form) would make every
        # v2-detection consumer treat migrated DAGs as v1 and recreate v1 schedules
        listings = [
            self._listing("dag-a:900", "data-modeling-execute-dag"),
            self._listing("dag-a:86400", "data-modeling-execute-dag"),
            self._listing("dag-b", "data-modeling-execute-dag"),
            self._listing("dag-c:86400:120", "data-modeling-execute-dag"),
        ]

        async def fake_list_schedules(*args, **kwargs):
            async def gen():
                for listing in listings:
                    yield listing

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules
        with mock.patch(
            "products.data_modeling.backend.schedule.async_connect",
            new=mock.AsyncMock(return_value=temporal),
        ):
            result = get_v2_scheduled_dag_ids()

        assert result == {"dag-a", "dag-b", "dag-c"}

    def test_empty_candidates_skips_temporal(self):
        connect = mock.AsyncMock()
        with mock.patch("products.data_modeling.backend.schedule.async_connect", new=connect):
            result = get_v2_scheduled_dag_ids(set())
        assert result == set()
        connect.assert_not_called()


EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class TestAnchoredSpec:
    # anchored specs fire at t ≡ anchor (mod interval), t in minutes from Monday 00:00 UTC
    @pytest.mark.parametrize(
        "interval,anchor,expected_hours,expected_minutes",
        [
            # 24h @ 00:00: exactly midnight
            (timedelta(hours=24), 0, {0}, {0}),
            # 6h @ 07:30: phase 1:30, so 01:30 / 07:30 / 13:30 / 19:30
            (timedelta(hours=6), 450, {1, 7, 13, 19}, {30}),
            # 12h @ 14:00: phase 2:00, so 02:00 / 14:00
            (timedelta(hours=12), 14 * 60, {2, 14}, {0}),
            # 15min @ 07:00: minute phase 0, every quarter-hour of every hour
            (timedelta(minutes=15), 420, set(range(24)), {0, 15, 30, 45}),
            # 30min @ xx:40: minute phase 10
            (timedelta(minutes=30), 40, set(range(24)), {10, 40}),
            # 1h @ 01:30: minute phase 30
            (timedelta(hours=1), 90, set(range(24)), {30}),
            # the day part of a week-based anchor is inert below weekly cadence:
            # Tuesday 02:00 (1560) on a daily schedule pins 02:00, same as anchor 120
            (timedelta(hours=24), 1560, {2}, {0}),
        ],
    )
    def test_fire_times(self, interval, anchor, expected_hours, expected_minutes):
        spec = build_schedule_spec(uuid.uuid4(), interval, anchor_minutes=anchor)
        calendar = spec.calendars[0]
        hours = {h for r in calendar.hour for h in range(r.start, r.end + 1)}
        minutes = {m for r in calendar.minute for m in range(r.start, r.end + 1)}
        assert hours == expected_hours
        assert minutes == expected_minutes

    def test_weekly_anchor_pins_day_of_week(self):
        # anchor counts days from Monday; Temporal counts day_of_week from Sunday (0),
        # so Tuesday 02:00 (minute 1560) must land on Temporal day 2, not day 1
        spec = build_schedule_spec(uuid.uuid4(), timedelta(days=7), anchor_minutes=1560)
        calendar = spec.calendars[0]
        assert [(r.start, r.end) for r in calendar.day_of_week] == [(2, 2)]
        assert [(r.start, r.end) for r in calendar.hour] == [(2, 2)]
        assert [(r.start, r.end) for r in calendar.minute] == [(0, 0)]

    def test_monthly_anchor_fires_on_the_source_30_day_grid(self):
        # a 30-day warehouse source syncs on days where days_since_epoch % 30 == 0, so an
        # anchored monthly tier has to land on that grid to read the sync it was pinned for
        spec = build_schedule_spec(uuid.uuid4(), timedelta(days=30), anchor_minutes=150)
        every, offset = spec.intervals[0].every, spec.intervals[0].offset
        assert every == timedelta(days=30)
        assert offset is not None  # a missing offset would drop the pin back to grid midnight
        fires = [EPOCH + offset + n * every for n in range(6)]
        assert {(fire - EPOCH).days % 30 for fire in fires} == {0}
        assert {(fire.hour, fire.minute) for fire in fires} == {(2, 30)}

    def test_monthly_ignores_the_anchors_day_component(self):
        # a 30-day cycle has no fixed weekday, so Tuesday 02:30 can only mean 02:30
        tuesday = build_schedule_spec(uuid.uuid4(), timedelta(days=30), anchor_minutes=1590)
        time_only = build_schedule_spec(uuid.uuid4(), timedelta(days=30), anchor_minutes=150)
        assert tuesday.intervals == time_only.intervals

    @pytest.mark.parametrize(
        "interval",
        [timedelta(minutes=15), timedelta(hours=24), timedelta(days=7), timedelta(days=30)],
    )
    def test_anchored_specs_are_utc_with_tight_jitter(self, interval):
        # the hash paths jitter up to 1hr and honor team timezone; a pin of 00:00 that
        # drifts an hour or shifts with DST is not a pin
        spec = build_schedule_spec(uuid.uuid4(), interval, team_timezone="US/Eastern", anchor_minutes=0)
        assert spec.time_zone_name == "UTC"
        assert spec.jitter == timedelta(minutes=1)
