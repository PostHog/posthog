import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.common.metrics import record_schedule_to_start_latency


class TestRecordScheduleToStartLatency:
    @pytest.mark.parametrize(
        "started_offset,expected",
        [
            (dt.timedelta(milliseconds=250), dt.timedelta(milliseconds=250)),
            (dt.timedelta(seconds=-3), dt.timedelta(0)),
        ],
        ids=["positive", "negative_clock_skew"],
    )
    def test_records_latency_clamped_to_zero(self, started_offset, expected):
        scheduled = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        mock_meter = MagicMock()

        with patch("posthog.temporal.common.metrics.get_metric_meter", return_value=mock_meter):
            record_schedule_to_start_latency(
                "test_histogram",
                scheduled_time=scheduled,
                started_time=scheduled + started_offset,
                description="test",
            )

        mock_meter.create_histogram_timedelta.return_value.record.assert_called_once_with(expected)

    def test_metric_failure_does_not_raise(self):
        mock_meter = MagicMock()
        mock_meter.create_histogram_timedelta.return_value.record.side_effect = ValueError(
            "Metric value cannot be negative"
        )
        scheduled = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

        with patch("posthog.temporal.common.metrics.get_metric_meter", return_value=mock_meter):
            record_schedule_to_start_latency(
                "test_histogram",
                scheduled_time=scheduled,
                started_time=scheduled,
                description="test",
            )
