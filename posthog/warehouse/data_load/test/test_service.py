import unittest
from datetime import timedelta
from temporalio.client import ScheduleCalendarSpec, ScheduleRange

from posthog.warehouse.data_load.service import get_calendar_spec


class TestGetCalendarSpec(unittest.TestCase):
    def test_basic_daily_schedule(self):
        # Test with daily schedule at midnight, expect 1 execution per day
        result = get_calendar_spec(0, 0, timedelta(days=1))
        expected = ScheduleCalendarSpec(
            hour=[ScheduleRange(start=0, end=0, step=24)], minute=[ScheduleRange(start=0, end=0, step=1)]
        )
        self.assertEqual(result.hour, expected.hour)
        self.assertEqual(result.minute, expected.minute)

    def test_every_6_hours_at_12_am(self):
        # Test with 6 hour frequency staring at 12:00, expect 4 executions per day
        result = get_calendar_spec(0, 0, timedelta(hours=6))
        expected = ScheduleCalendarSpec(
            hour=[ScheduleRange(start=0, end=18, step=6)], minute=[ScheduleRange(start=0, end=0, step=1)]
        )
        self.assertEqual(result.hour, expected.hour)
        self.assertEqual(result.minute, expected.minute)

    def test_every_6_hours(self):
        # Test with 6-hour frequency starting at 3:00, expect 4 executions per day
        result = get_calendar_spec(3, 0, timedelta(hours=6))
        expected = ScheduleCalendarSpec(
            hour=[ScheduleRange(start=3, end=21, step=6)], minute=[ScheduleRange(start=0, end=0, step=1)]
        )
        self.assertEqual(result.hour, expected.hour)
        self.assertEqual(result.minute, expected.minute)

    def test_every_12_hours(self):
        # Test with 12-hour frequency starting at 6:30, expect 2 executions per day
        result = get_calendar_spec(6, 30, timedelta(hours=12))
        expected = ScheduleCalendarSpec(
            hour=[ScheduleRange(start=6, end=18, step=12)], minute=[ScheduleRange(start=30, end=30, step=1)]
        )
        self.assertEqual(result.hour, expected.hour)
        self.assertEqual(result.minute, expected.minute)

    def test_odd_hour_frequency(self):
        # Test with 5-hour frequency starting at 2:15
        result = get_calendar_spec(2, 15, timedelta(hours=5))
        expected = ScheduleCalendarSpec(
            hour=[ScheduleRange(start=2, end=22, step=5)], minute=[ScheduleRange(start=15, end=15, step=1)]
        )
        self.assertEqual(result.hour, expected.hour)
        self.assertEqual(result.minute, expected.minute)

    def test_late_start_time(self):
        # Test with 8-hour frequency starting at 22:00, expect 1 execution per day
        result = get_calendar_spec(22, 0, timedelta(hours=8))
        expected = ScheduleCalendarSpec(
            hour=[ScheduleRange(start=22, end=22, step=8)], minute=[ScheduleRange(start=0, end=0, step=1)]
        )
        self.assertEqual(result.hour, expected.hour)
        self.assertEqual(result.minute, expected.minute)

    def test_frequency_larger_than_day(self):
        result = get_calendar_spec(9, 45, timedelta(hours=36))
        expected = ScheduleCalendarSpec(
            hour=[ScheduleRange(start=9, end=9, step=36)], minute=[ScheduleRange(start=45, end=45, step=1)]
        )
        self.assertEqual(result.hour, expected.hour)
        self.assertEqual(result.minute, expected.minute)
