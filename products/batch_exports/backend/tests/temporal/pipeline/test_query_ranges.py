"""Tests for choosing which ranges and tables a batch export run queries."""

import typing
import datetime as dt

import pytest

from products.batch_exports.backend.service import BackfillDetails
from products.batch_exports.backend.temporal.pipeline.query_ranges import use_distributed_events_recent_table

pytestmark = [pytest.mark.django_db]


@pytest.mark.parametrize(
    "test_data",
    [
        # isn't a backfill so should use distributed_events_recent table
        {
            "is_backfill": False,
            "data_interval_start": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1),
            "use_distributed_events_recent_table": True,
        },
        # is a backfill within the last 6 days so should use distributed_events_recent table
        {
            "is_backfill": True,
            "backfill_start_at": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1),
            "data_interval_start": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1),
            "use_distributed_events_recent_table": True,
        },
        # is a backfill outside the last 6 days so shouldn't use distributed_events_recent table
        {
            "is_backfill": True,
            "backfill_start_at": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=7),
            "data_interval_start": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1),
            "use_distributed_events_recent_table": False,
        },
    ],
)
def test_use_distributed_events_recent_table(test_data: dict[str, typing.Any]):
    backfill_details = (
        BackfillDetails(
            backfill_id=None,
            start_at=test_data["backfill_start_at"].isoformat(),
            end_at=(test_data["backfill_start_at"] + dt.timedelta(days=1)).isoformat(),
            is_earliest_backfill=False,
        )
        if test_data["is_backfill"]
        else None
    )
    assert (
        use_distributed_events_recent_table(
            test_data["is_backfill"], backfill_details, data_interval_start=test_data["data_interval_start"]
        )
        == test_data["use_distributed_events_recent_table"]
    )
