from datetime import date

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.ducklake.backfill_telemetry import BACKFILL_PARTITION_EVENT, emit_backfill_partition_event


class TestBackfillTelemetry(BaseTest):
    def test_emits_event_with_properties(self) -> None:
        capture = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=capture)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("posthog.ducklake.backfill_telemetry.ph_scoped_capture", return_value=cm):
            emit_backfill_partition_event(
                partition_date=date(2020, 5, 1), status="success", run_id="r1", rows_exported=99
            )
        capture.assert_called_once()
        kwargs = capture.call_args.kwargs
        assert kwargs["event"] == BACKFILL_PARTITION_EVENT
        assert kwargs["properties"]["partition_date"] == "2020-05-01"
        assert kwargs["properties"]["status"] == "success"
        assert kwargs["properties"]["rows_exported"] == 99
