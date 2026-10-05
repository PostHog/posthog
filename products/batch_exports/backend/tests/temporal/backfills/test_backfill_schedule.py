import uuid
import datetime as dt
import dataclasses

import pytest
from unittest import mock

from products.batch_exports.backend.temporal.backfill_batch_export import (
    BACKFILL_SCHEDULE_MAX_ATTEMPTS_WITHOUT_PROGRESS,
    BackfillScheduleInputs,
    BackfillScheduleNoProgressError,
    HeartbeatDetailsParseError,
    backfill_schedule,
)

from .conftest import assert_backfill_details_in_workflow_events, wait_for_workflows


async def test_backfill_schedule_activity(
    activity_environment, temporal_worker, temporal_client, temporal_schedule_hourly
):
    """Test backfill_schedule activity schedules all backfill runs."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 5, 0, 0, tzinfo=dt.UTC)
    backfill_id = str(uuid.uuid4())

    desc = await temporal_schedule_hourly.describe()
    inputs = BackfillScheduleInputs(
        schedule_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=0.1,
        frequency_seconds=desc.schedule.spec.intervals[0].every.total_seconds(),
        backfill_id=backfill_id,
    )

    await activity_environment.run(backfill_schedule, inputs)

    workflows = await wait_for_workflows(temporal_client, desc.id, expected_count=5)

    await assert_backfill_details_in_workflow_events(
        temporal_client,
        workflows,
        expected_backfill_id=backfill_id,
        expected_start_at=start_at.isoformat(),
        expected_end_at=end_at.isoformat(),
        expected_is_earliest_backfill=False,
    )


@pytest.mark.parametrize(
    "corrupted_details",
    [
        ("", "", "", ""),  # one extra item should fail parsing
        ("", ""),  # one less item should fail parsing
    ],
)
async def test_backfill_schedule_activity_fails_with_corrupted_details(
    activity_environment,
    temporal_worker,
    temporal_client,
    temporal_schedule_hourly,
    corrupted_details,
):
    """Test backfill_schedule activity fails when details are corrupted."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 5, 0, 0, tzinfo=dt.UTC)
    backfill_id = str(uuid.uuid4())

    desc = await temporal_schedule_hourly.describe()
    inputs = BackfillScheduleInputs(
        schedule_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=0.1,
        frequency_seconds=desc.schedule.spec.intervals[0].every.total_seconds(),
        backfill_id=backfill_id,
    )

    activity_environment.info = dataclasses.replace(activity_environment.info, heartbeat_details=corrupted_details)

    with pytest.raises(HeartbeatDetailsParseError):
        await activity_environment.run(backfill_schedule, inputs)


@pytest.mark.parametrize(
    "attempt,heartbeat_details,expected_error",
    [
        (BACKFILL_SCHEDULE_MAX_ATTEMPTS_WITHOUT_PROGRESS - 1, (), ConnectionError),
        (BACKFILL_SCHEDULE_MAX_ATTEMPTS_WITHOUT_PROGRESS, (), BackfillScheduleNoProgressError),
        (
            BACKFILL_SCHEDULE_MAX_ATTEMPTS_WITHOUT_PROGRESS,
            ("schedule-id", "workflow-id", "2023-01-01T01:00:00+00:00"),
            ConnectionError,
        ),
    ],
)
async def test_backfill_schedule_activity_fails_without_progress_after_max_attempts(
    activity_environment, attempt, heartbeat_details, expected_error
):
    inputs = BackfillScheduleInputs(
        schedule_id="schedule-id",
        start_at="2023-01-01T00:00:00+00:00",
        end_at="2023-01-01T05:00:00+00:00",
        start_delay=0.1,
        frequency_seconds=3600,
        backfill_id=str(uuid.uuid4()),
    )
    activity_environment.info = dataclasses.replace(
        activity_environment.info, attempt=attempt, heartbeat_details=heartbeat_details
    )

    with mock.patch(
        "products.batch_exports.backend.temporal.backfill_batch_export.connect",
        side_effect=ConnectionError("namespace rate limit exceeded"),
    ):
        with pytest.raises(expected_error, match="namespace rate limit exceeded"):
            await activity_environment.run(backfill_schedule, inputs)
