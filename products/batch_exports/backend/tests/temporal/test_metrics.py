import asyncio
import datetime as dt

import pytest

from structlog.testing import capture_logs

from products.batch_exports.backend.temporal.metrics import ExecutionTimeRecorder, SLAWaiter, get_interval_from_bounds

pytestmark = [pytest.mark.asyncio]


@pytest.mark.parametrize(
    "data_interval_start,data_interval_end,on_demand,expected",
    [
        (None, None, True, "on_demand"),
        ("2023-01-01T00:00:00+00:00", None, True, "on_demand"),
        (None, "2023-01-01T01:00:00+00:00", True, "on_demand"),
        (None, "2023-01-01T01:00:00+00:00", False, "beginning_of_time"),
        ("2023-01-01T00:00:00+00:00", None, False, None),
    ],
)
async def test_interval_from_optional_bounds(
    data_interval_start: str | None, data_interval_end: str | None, on_demand: bool, expected: str | None
) -> None:
    assert get_interval_from_bounds(data_interval_start, data_interval_end, on_demand=on_demand) == expected


async def test_sla_waiter():
    with capture_logs() as cap_logs:
        async with SLAWaiter(batch_export_id="test", sla=dt.timedelta(seconds=0.25)) as detector:
            await asyncio.sleep(0.75)

            assert detector.is_over_sla()

    assert "SLA breached" == cap_logs[0]["event"]
    assert "test" == cap_logs[0]["batch_export_id"]
    assert 0.25 == cap_logs[0]["sla_seconds"]

    with capture_logs() as cap_logs:
        async with SLAWaiter(batch_export_id="test", sla=dt.timedelta(seconds=0.75)) as detector:
            await asyncio.sleep(0.25)

            assert detector.is_over_sla() is False

    assert not cap_logs


async def test_execution_time_recorder_only_logs_outside_temporal(settings):
    """Warehouse source writers run ParquetStreamTransformer outside Temporal, where a metric meter is not
    available. With DEBUG and TEST set, get_metric_meter returns a no-op meter, so they are unset here to check
    that the recorder does not raise.
    """
    settings.DEBUG = False
    settings.TEST = False

    with capture_logs() as cap_logs:
        with ExecutionTimeRecorder("test_duration"):
            pass

    assert len(cap_logs) == 1
    assert "test_duration" in cap_logs[0]["event"]
