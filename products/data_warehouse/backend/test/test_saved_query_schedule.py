import uuid
from datetime import timedelta

from unittest.mock import MagicMock

from django.test import TestCase

from parameterized import parameterized

from products.data_warehouse.backend.data_load.saved_query_service import get_saved_query_schedule


class TestGetSavedQuerySchedule(TestCase):
    def _make_saved_query(self, sync_frequency_interval: timedelta | None = None, timezone: str = "UTC") -> MagicMock:
        sq = MagicMock()
        sq.id = uuid.uuid4()
        sq.team_id = 1
        sq.pk = sq.id
        sq.sync_frequency_interval = sync_frequency_interval
        sq.team.timezone = timezone
        return sq

    def test_uses_calendar_spec(self):
        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=24))
        schedule = get_saved_query_schedule(sq)
        assert len(schedule.spec.calendars) >= 1

    def test_defaults_to_24h_when_no_interval(self):
        sq = self._make_saved_query(sync_frequency_interval=None)
        schedule = get_saved_query_schedule(sq)
        # 24hr -> medium tier -> 1 hour entry
        assert len(schedule.spec.calendars) == 1
        assert len(schedule.spec.calendars[0].hour) == 1

    def test_passes_team_timezone(self):
        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=24), timezone="America/New_York")
        schedule = get_saved_query_schedule(sq)
        assert schedule.spec.time_zone_name == "America/New_York"

    @parameterized.expand(
        [
            ("15min", timedelta(minutes=15)),
            ("30min", timedelta(minutes=30)),
            ("1h", timedelta(hours=1)),
            ("6h", timedelta(hours=6)),
            ("12h", timedelta(hours=12)),
            ("24h", timedelta(hours=24)),
            ("7d", timedelta(days=7)),
            ("30d", timedelta(days=30)),
        ]
    )
    def test_deterministic_for_same_id(self, _name, interval):
        sq = self._make_saved_query(sync_frequency_interval=interval)
        schedule_a = get_saved_query_schedule(sq)
        schedule_b = get_saved_query_schedule(sq)
        assert schedule_a.spec.calendars == schedule_b.spec.calendars

    def test_schedule_has_cancel_other_overlap_policy(self):
        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=6))
        schedule = get_saved_query_schedule(sq)
        from temporalio.client import ScheduleOverlapPolicy

        assert schedule.policy.overlap == ScheduleOverlapPolicy.CANCEL_OTHER

    def test_schedule_action_is_data_modeling_run(self):
        from temporalio.client import ScheduleActionStartWorkflow

        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=6))
        schedule = get_saved_query_schedule(sq)
        assert isinstance(schedule.action, ScheduleActionStartWorkflow)
        assert schedule.action.workflow == "data-modeling-run"
