from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import pytest
from unittest.mock import MagicMock, patch

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.tasks.report_utils import capture_event
from posthog.temporal.usage_report.experimental_realtime import (
    EXPERIMENTAL_REALTIME_USAGE_EVENT,
    MANUAL_EXPERIMENTAL_REALTIME_USAGE_EVENT,
    ExperimentalRealtimeUsageContext,
    GatherExperimentalRealtimeUsageInputs,
    GatherExperimentalRealtimeUsageResult,
    GatherExperimentalRealtimeUsageWorkflow,
    UsageSnapshot,
    build_usage_snapshots,
    capture_usage_snapshots,
    experimental_usage_event_uuid,
    gather_experimental_realtime_usage,
    get_canonical_usage_rows,
)


def test_build_usage_snapshots_discovers_keys_and_preserves_unit_conflicts() -> None:
    snapshots = build_usage_snapshots(
        [
            ("org-1", "producer-a", "new_key", "requests", 3),
            ("org-1", "producer-b", "new_key", "requests", 4),
            ("org-1", "producer-a", "ambiguous_key", "bytes", 1),
            ("org-1", "producer-b", "ambiguous_key", "records", 2),
            ("org-2", "producer-a", "another_new_key", "credits", 5),
        ]
    )

    assert [snapshot.organization_id for snapshot in snapshots] == ["org-1", "org-2"]
    assert snapshots[0].usage_by_key == {"new_key": 7}
    assert snapshots[0].unit_by_key == {"new_key": "requests"}
    assert snapshots[0].unit_conflicts == {"ambiguous_key": ["bytes", "records"]}
    assert snapshots[0].usage_by_producer == {
        "producer-a": {
            "new_key": {"requests": 3},
            "ambiguous_key": {"bytes": 1},
        },
        "producer-b": {
            "new_key": {"requests": 4},
            "ambiguous_key": {"records": 2},
        },
    }
    assert snapshots[1].usage_by_key == {"another_new_key": 5}


def test_capture_usage_snapshots_uses_stable_experimental_event_uuid() -> None:
    ctx = ExperimentalRealtimeUsageContext(
        period_start=datetime(2026, 5, 4, tzinfo=UTC),
        period_end=datetime(2026, 5, 5, tzinfo=UTC),
        snapshot_at=datetime(2026, 5, 4, 12, 30, tzinfo=UTC),
        report_completeness="partial",
    )
    snapshot = UsageSnapshot(
        organization_id="org-1",
        usage_by_key={"events": 7},
        unit_by_key={"events": "events"},
        usage_by_producer={"ingestion": {"events": {"events": 7}}},
        unit_conflicts={},
    )
    client = MagicMock()

    with (
        patch("posthog.temporal.usage_report.experimental_realtime.get_ph_client", return_value=client),
        patch("posthog.temporal.usage_report.experimental_realtime.capture_event") as capture_event,
    ):
        assert capture_usage_snapshots([snapshot], ctx, EXPERIMENTAL_REALTIME_USAGE_EVENT) == 1
        assert capture_usage_snapshots([snapshot], ctx, EXPERIMENTAL_REALTIME_USAGE_EVENT) == 1

    expected_uuid = experimental_usage_event_uuid("org-1", ctx)
    assert isinstance(expected_uuid, UUID)
    assert capture_event.call_count == 2
    for call in capture_event.call_args_list:
        assert call.kwargs["name"] == EXPERIMENTAL_REALTIME_USAGE_EVENT
        assert call.kwargs["event_uuid"] == expected_uuid
        assert call.kwargs["distinct_id"] == "org-org-1"
        assert call.kwargs["properties"]["experimental"] is True
        assert call.kwargs["properties"]["source"] == "billing_usage_records"
    assert client.flush.call_count == 2


def test_capture_event_passes_explicit_event_uuid() -> None:
    client = MagicMock()
    event_uuid = uuid4()

    with patch("posthog.tasks.report_utils.is_cloud", return_value=True):
        capture_event(
            pha_client=client,
            name=EXPERIMENTAL_REALTIME_USAGE_EVENT,
            organization_id="org-1",
            distinct_id="org-org-1",
            event_uuid=event_uuid,
            properties={},
        )

    assert client.capture.call_args.kwargs["uuid"] == event_uuid


def test_canonical_query_uses_the_complete_replacement_identity() -> None:
    ctx = ExperimentalRealtimeUsageContext(
        period_start=datetime(2026, 5, 4, tzinfo=UTC),
        period_end=datetime(2026, 5, 5, tzinfo=UTC),
        snapshot_at=datetime(2026, 5, 5, tzinfo=UTC),
        report_completeness="complete",
        organization_ids=["00000000-0000-0000-0000-000000000001"],
    )

    with patch(
        "posthog.temporal.usage_report.experimental_realtime.sync_execute",
        return_value=[("00000000-0000-0000-0000-000000000001", "ingestion", "events", "events", 7)],
    ) as sync_execute:
        rows = get_canonical_usage_rows(ctx)

    query = sync_execute.call_args.args[0]
    assert "GROUP BY team_id, toDate(timestamp), producer_id, usage_key, record_id" in query
    assert "argMax(quantity, inserted_at)" in query
    assert "organization_id IN %(organization_ids)s" in query
    assert rows == [("00000000-0000-0000-0000-000000000001", "ingestion", "events", "events", 7)]


def test_workflow_parses_manual_mode_for_management_command() -> None:
    inputs = GatherExperimentalRealtimeUsageWorkflow.parse_inputs(['{"day_offset": 1, "mode": "manual_report"}'])

    assert inputs == GatherExperimentalRealtimeUsageInputs(day_offset=1, mode="manual_report")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_event_name,expected_captured",
    [
        ("capture", EXPERIMENTAL_REALTIME_USAGE_EVENT, 1),
        ("manual_report", MANUAL_EXPERIMENTAL_REALTIME_USAGE_EVENT, 1),
        ("dry_run", None, 0),
    ],
)
async def test_activity_respects_capture_mode(
    mode: Literal["capture", "manual_report", "dry_run"],
    expected_event_name: str | None,
    expected_captured: int,
    activity_environment,
) -> None:
    ctx = ExperimentalRealtimeUsageContext(
        period_start=datetime(2026, 5, 4, tzinfo=UTC),
        period_end=datetime(2026, 5, 5, tzinfo=UTC),
        snapshot_at=datetime(2026, 5, 5, tzinfo=UTC),
        report_completeness="complete",
        mode=mode,
    )
    with (
        patch(
            "posthog.temporal.usage_report.experimental_realtime.get_canonical_usage_rows",
            return_value=[("org-1", "ingestion", "events", "events", 7)],
        ),
        patch("posthog.temporal.usage_report.experimental_realtime.capture_usage_snapshots", return_value=1) as capture,
    ):
        result = await activity_environment.run(gather_experimental_realtime_usage, ctx)

    assert result.organizations_found == 1
    assert result.organizations_captured == expected_captured
    if expected_event_name is None:
        capture.assert_not_called()
    else:
        capture.assert_called_once()
        assert capture.call_args.args[1:] == (ctx, expected_event_name)


@pytest.mark.asyncio
async def test_workflow_passes_only_context_to_the_gathering_activity() -> None:
    seen_contexts: list[ExperimentalRealtimeUsageContext] = []
    expected_result = GatherExperimentalRealtimeUsageResult(
        canonical_row_count=2,
        organizations_found=1,
        organizations_captured=1,
        usage_key_count=2,
        query_duration_ms=1,
        capture_duration_ms=1,
    )

    @activity.defn(name="gather-experimental-realtime-usage")
    async def gather_mock(ctx: ExperimentalRealtimeUsageContext) -> GatherExperimentalRealtimeUsageResult:
        seen_contexts.append(ctx)
        return expected_result

    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue="experimental-realtime-usage-test",
            workflows=[GatherExperimentalRealtimeUsageWorkflow],
            activities=[gather_mock],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                GatherExperimentalRealtimeUsageWorkflow.run,
                GatherExperimentalRealtimeUsageInputs(day_offset=1, organization_ids=["org-1"], mode="manual_report"),
                id="experimental-realtime-usage-test-workflow",
                task_queue="experimental-realtime-usage-test",
            )

    assert result == expected_result
    assert seen_contexts[0].organization_ids == ["org-1"]
    assert seen_contexts[0].report_completeness == "complete"
    assert seen_contexts[0].mode == "manual_report"


@pytest.mark.asyncio
async def test_workflow_rejects_negative_day_offset() -> None:
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue="experimental-realtime-usage-negative-offset-test",
            workflows=[GatherExperimentalRealtimeUsageWorkflow],
            activities=[],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError) as exc_info:
                await env.client.execute_workflow(
                    GatherExperimentalRealtimeUsageWorkflow.run,
                    GatherExperimentalRealtimeUsageInputs(day_offset=-1),
                    id="experimental-realtime-usage-negative-offset-test-workflow",
                    task_queue="experimental-realtime-usage-negative-offset-test",
                )

    cause = exc_info.value.cause
    assert isinstance(cause, ApplicationError)
    assert cause.non_retryable
