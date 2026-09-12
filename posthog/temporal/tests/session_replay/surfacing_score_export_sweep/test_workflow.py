import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import NoReturn

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
    export_encrypted_scores_page_activity,
    export_scores_partition_activity,
    list_export_partitions_activity,
    plan_encrypted_score_ranges_activity,
    publish_encrypted_score_manifest_activity,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import MAX_CONCURRENT_EXPORT_PARTITIONS
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
    EncryptedScoreExport,
    EncryptedScoreManifest,
    EncryptedScorePage,
    EncryptedScorePageResult,
    EncryptedScorePlan,
    EncryptedScorePlanInput,
    ExportPartitionResult,
    ExportPartitionSpec,
    ExportScoresSweepInputs,
    ListExportPartitionsResult,
    ScoreCursor,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.workflow import (
    ExportEncryptedScoresWorkflow,
    ExportSurfacingScoresWorkflow,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "encrypted,page_limit,shape",
    [
        (False, 100, "normal"),
        (True, 100, "normal"),
        (True, 1, "normal"),
        (True, 1, "overflow"),
        (True, 1, "next_plan"),
        (True, 1, "empty"),
    ],
)
async def test_bounds_concurrent_partition_activities(encrypted: bool, page_limit: int, shape: str) -> None:
    partition_count = MAX_CONCURRENT_EXPORT_PARTITIONS + 3
    partitions = [
        ExportPartitionSpec(day="2026-07-14", chunk_id=chunk_id, of_chunks=partition_count, encrypted_enabled=encrypted)
        for chunk_id in range(partition_count)
    ]
    active = 0
    peak_active = 0
    completed_pages: dict[int, int] = {}
    published: set[int] = set()
    expected_pages = 0 if shape == "empty" else 3 if shape == "overflow" else 2
    planned: dict[int, int] = {}

    async def execute_activity(
        activity: object, activity_input: object, **_: object
    ) -> ListExportPartitionsResult | ExportPartitionResult | EncryptedScorePlan | EncryptedScorePageResult | None:
        nonlocal active, peak_active

        if activity is list_export_partitions_activity:
            return ListExportPartitionsResult(partitions=partitions)

        if activity is plan_encrypted_score_ranges_activity:
            assert isinstance(activity_input, EncryptedScorePlanInput)
            planned[activity_input.partition.chunk_id] = planned.get(activity_input.partition.chunk_id, 0) + 1
            boundaries = [ScoreCursor(team_id=7, session_id="first"), ScoreCursor(team_id=8, session_id="last")]
            if shape == "empty":
                return EncryptedScorePlan(boundaries=[], has_more=False)
            if shape == "next_plan":
                first_plan = activity_input.cursor == ScoreCursor()
                return EncryptedScorePlan(
                    boundaries=boundaries[:1] if first_plan else boundaries[1:], has_more=first_plan
                )
            return EncryptedScorePlan(boundaries=boundaries, has_more=False)
        if activity is export_encrypted_scores_page_activity:
            assert isinstance(activity_input, EncryptedScorePage)
            assert activity_input.page == completed_pages.get(activity_input.partition.chunk_id, 0)
            completed_pages[activity_input.partition.chunk_id] = activity_input.page + 1
            next_page = None
            if shape == "overflow" and activity_input.page == 0:
                next_page = replace(activity_input, page=1, cursor=ScoreCursor(team_id=7, session_id="before-first"))
            elif shape == "overflow" and activity_input.page == 1:
                assert activity_input.cursor == ScoreCursor(team_id=7, session_id="before-first")
                assert activity_input.upper == ScoreCursor(team_id=7, session_id="first")
            return EncryptedScorePageResult(
                rows=2,
                bytes_written=100,
                next_page=next_page,
                session_months=["2026-09" if activity_input.page == 0 else "2026-10"],
            )
        if activity is publish_encrypted_score_manifest_activity:
            assert isinstance(activity_input, EncryptedScoreManifest)
            assert activity_input.pages == completed_pages.get(activity_input.partition.chunk_id, 0) == expected_pages
            assert activity_input.session_months == ([] if shape == "empty" else ["2026-09", "2026-10"])
            published.add(activity_input.partition.chunk_id)
            return None
        assert activity is export_scores_partition_activity
        assert isinstance(activity_input, ExportPartitionSpec)
        active += 1
        peak_active = max(peak_active, active)
        try:
            await asyncio.sleep(0)
            return ExportPartitionResult(day=activity_input.day, chunk_id=activity_input.chunk_id, rows=1)
        finally:
            active -= 1

    class ContinueAsNew(Exception):
        def __init__(self, inputs: EncryptedScoreExport) -> None:
            self.inputs = inputs

    def continue_as_new(inputs: EncryptedScoreExport) -> NoReturn:
        raise ContinueAsNew(inputs)

    async def execute_child_workflow(
        _: object, inputs: EncryptedScoreExport, **options: object
    ) -> ExportPartitionResult:
        while True:
            try:
                return await ExportEncryptedScoresWorkflow().run(inputs)
            except ContinueAsNew as continuation:
                assert continuation.inputs.pages > inputs.pages
                assert continuation.inputs.export_id == inputs.export_id
                inputs = continuation.inputs

    with (
        patch("temporalio.workflow.execute_activity", side_effect=execute_activity),
        patch("temporalio.workflow.execute_child_workflow", side_effect=execute_child_workflow),
        patch("temporalio.workflow.continue_as_new", side_effect=continue_as_new),
        patch(
            "posthog.temporal.session_replay.surfacing_score_export_sweep.workflow.MAX_ENCRYPTED_PAGES_PER_RUN",
            page_limit,
        ),
        patch("temporalio.workflow.patched", return_value=True),
        patch("temporalio.workflow.logger", MagicMock()),
        patch(
            "temporalio.workflow.info",
            return_value=MagicMock(start_time=datetime(2026, 9, 15, tzinfo=UTC), run_id="test-run"),
        ),
        patch(
            "posthog.temporal.session_replay.surfacing_score_export_sweep.workflow.record_tick_summary"
        ) as record_summary,
    ):
        result = await ExportSurfacingScoresWorkflow().run(ExportScoresSweepInputs())

    assert peak_active == MAX_CONCURRENT_EXPORT_PARTITIONS
    assert result.partitions_dispatched == partition_count
    assert result.total_rows == partition_count * (1 + 2 * expected_pages if encrypted else 1)
    assert len(published) == (partition_count if encrypted else 0)
    assert all(count == (2 if shape == "next_plan" else 1) for count in planned.values())
    record_summary.assert_called_once_with(
        partitions_dispatched=partition_count, partitions_failed=0, total_rows=result.total_rows
    )
