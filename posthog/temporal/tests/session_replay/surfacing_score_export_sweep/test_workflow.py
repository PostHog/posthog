import asyncio

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
    export_scores_partition_activity,
    list_export_partitions_activity,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import MAX_CONCURRENT_EXPORT_PARTITIONS
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
    ExportPartitionResult,
    ExportPartitionSpec,
    ExportScoresSweepInputs,
    ListExportPartitionsResult,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.workflow import ExportSurfacingScoresWorkflow


@pytest.mark.asyncio
async def test_bounds_concurrent_partition_activities() -> None:
    partition_count = MAX_CONCURRENT_EXPORT_PARTITIONS + 3
    partitions = [
        ExportPartitionSpec(day="2026-07-14", chunk_id=chunk_id, of_chunks=partition_count)
        for chunk_id in range(partition_count)
    ]
    active = 0
    peak_active = 0

    async def execute_activity(
        activity: object, activity_input: object, **_: object
    ) -> ListExportPartitionsResult | ExportPartitionResult:
        nonlocal active, peak_active

        if activity is list_export_partitions_activity:
            return ListExportPartitionsResult(partitions=partitions)

        assert activity is export_scores_partition_activity
        assert isinstance(activity_input, ExportPartitionSpec)
        active += 1
        peak_active = max(peak_active, active)
        try:
            await asyncio.sleep(0)
            return ExportPartitionResult(day=activity_input.day, chunk_id=activity_input.chunk_id, rows=1)
        finally:
            active -= 1

    with (
        patch("temporalio.workflow.execute_activity", side_effect=execute_activity),
        patch("temporalio.workflow.patched", return_value=True),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        result = await ExportSurfacingScoresWorkflow().run(ExportScoresSweepInputs())

    assert peak_active == MAX_CONCURRENT_EXPORT_PARTITIONS
    assert result.partitions_dispatched == partition_count
    assert result.total_rows == partition_count
