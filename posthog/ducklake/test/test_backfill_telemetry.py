from datetime import date

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.ducklake.backfill_telemetry import BACKFILL_PARTITION_EVENT, emit_backfill_partition_event


class TestBackfillTelemetry(BaseTest):
    def test_emits_event_with_team_and_properties(self) -> None:
        capture = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=capture)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("posthog.ducklake.backfill_telemetry.ph_scoped_capture", return_value=cm):
            emit_backfill_partition_event(
                team_id=42,
                partition_date=date(2024, 5, 1),
                status="success",
                run_id="r1",
                files_exported=3,
            )
        capture.assert_called_once()
        props = capture.call_args.kwargs["properties"]
        assert capture.call_args.kwargs["event"] == BACKFILL_PARTITION_EVENT
        assert props["team_id"] == 42
        assert props["partition_date"] == "2024-05-01"
        assert props["status"] == "success"
        assert props["files_exported"] == 3
