import asyncio
import datetime as dt

import pytest

from structlog.testing import capture_logs

from products.batch_exports.backend.temporal.metrics import SLAWaiter

pytestmark = [pytest.mark.asyncio]


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
