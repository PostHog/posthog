import uuid
from datetime import timedelta

from unittest.mock import MagicMock

from django.test import TestCase

from parameterized import parameterized

from products.data_warehouse.backend.data_load.saved_query_service import _get_midnight_offset, get_saved_query_schedule


class TestGetMidnightOffset(TestCase):
    def test_deterministic_for_same_id(self):
        id = uuid.uuid4()
        assert _get_midnight_offset(id) == _get_midnight_offset(id)

    def test_different_ids_produce_different_offsets(self):
        offsets = {_get_midnight_offset(uuid.uuid4()) for _ in range(20)}
        assert len(offsets) > 1

    def test_offset_within_range(self):
        for _ in range(100):
            offset = _get_midnight_offset(uuid.uuid4())
            offset_seconds = offset.total_seconds()
            # offset should map to either [0, 3600] (12am - 1am) or [82800, 86400] (11pm - 12am)
            assert 0 <= offset_seconds < 86400
            in_window = offset_seconds <= 3600 or offset_seconds >= 82800
            assert in_window, f"Offset {offset_seconds}s is outside the 11PM-1AM UTC window"

    def test_offset_is_positive(self):
        for _ in range(50):
            offset = _get_midnight_offset(uuid.uuid4())
            assert offset >= timedelta()


class TestGetSavedQuerySchedule(TestCase):
    def _make_saved_query(self, sync_frequency_interval: timedelta | None = None) -> MagicMock:
        sq = MagicMock()
        sq.id = uuid.uuid4()
        sq.team_id = 1
        sq.pk = sq.id
        sq.sync_frequency_interval = sync_frequency_interval
        return sq

    @parameterized.expand(
        [
            ("1h", timedelta(hours=1)),
            ("6h", timedelta(hours=6)),
            ("12h", timedelta(hours=12)),
        ]
    )
    def test_sub_24h_interval_has_zero_offset(self, _name, interval):
        sq = self._make_saved_query(sync_frequency_interval=interval)
        schedule = get_saved_query_schedule(sq)
        offset = schedule.spec.intervals[0].offset
        assert offset == timedelta(), f"Expected zero offset for interval={interval}"

    def test_24h_offset_in_11pm_1am_window(self):
        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=24))
        schedule = get_saved_query_schedule(sq)
        offset = schedule.spec.intervals[0].offset
        assert offset is not None, "Expected non-None offset for 24h interval"
        offset_seconds = offset.total_seconds()
        in_window = offset_seconds <= 3600 or offset_seconds >= 82800
        assert in_window, f"Offset {offset_seconds}s is outside the 11PM-1AM UTC window"
