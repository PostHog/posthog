import uuid
import datetime as dt

import pytest

from posthog.management.commands.migrate_team import DATA_START_UNBOUNDED, get_migrated_data_start

from products.batch_exports.backend.facade.contracts import BatchExportBackfillStatus, BatchExportBackfillSummary

JAN_1 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
JAN_2 = JAN_1 + dt.timedelta(days=1)
JAN_3 = JAN_1 + dt.timedelta(days=2)


def _backfill(status: str, start_at: dt.datetime | None) -> BatchExportBackfillSummary:
    return BatchExportBackfillSummary(
        id=uuid.uuid4(),
        status=status,
        start_at=start_at,
        adjusted_start_at=None,
        created_at=JAN_3,
        last_updated_at=JAN_3,
    )


@pytest.mark.parametrize(
    "backfills,expected",
    [
        (
            [
                (BatchExportBackfillStatus.COMPLETED, JAN_3),
                (BatchExportBackfillStatus.RUNNING, JAN_2),
                (BatchExportBackfillStatus.FAILED, JAN_1),
            ],
            JAN_2,
        ),
        (
            [(BatchExportBackfillStatus.COMPLETED, JAN_2), (BatchExportBackfillStatus.COMPLETED, None)],
            DATA_START_UNBOUNDED,
        ),
        ([(BatchExportBackfillStatus.CANCELLED, None), (BatchExportBackfillStatus.COMPLETED, JAN_2)], JAN_2),
        ([(BatchExportBackfillStatus.FAILED, JAN_1), (BatchExportBackfillStatus.TIMEDOUT, JAN_2)], None),
    ],
    ids=["earliest of the backfills that did not fail", "no start is unbounded", "failed no start", "all failed"],
)
def test_migrated_data_start(backfills, expected):
    assert get_migrated_data_start([_backfill(status, start_at) for status, start_at in backfills]) == expected
