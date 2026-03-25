import uuid
from collections import Counter
from datetime import timedelta

from temporalio.client import ScheduleCalendarSpec

from products.data_modeling.backend.schedule import _deterministic_int, build_schedule_spec


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
