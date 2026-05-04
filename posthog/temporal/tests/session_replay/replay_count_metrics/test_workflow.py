import uuid

import pytest
from unittest.mock import AsyncMock, patch

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.replay_count_metrics.types import ReplayCountMetricsInput
from posthog.temporal.session_replay.replay_count_metrics.workflow import ReplayCountMetricsWorkflow


@pytest.mark.asyncio
async def test_workflow_calls_activity():
    activity_called = False

    @activity.defn(name="collect-replay-count-metrics")
    async def mock_collect(input: ReplayCountMetricsInput) -> None:
        nonlocal activity_called
        activity_called = True

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ReplayCountMetricsWorkflow],
            activities=[mock_collect],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ReplayCountMetricsWorkflow.run,
                ReplayCountMetricsInput(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert activity_called


@pytest.mark.asyncio
async def test_activity_pushes_metrics():
    mock_row = {
        "all_recordings": 1000,
        "mobile_recordings": 200,
        "web_recordings": 750,
        "invalid_web_recordings": 50,
    }

    mock_client = AsyncMock()
    mock_client.read_query_as_jsonl = AsyncMock(return_value=[mock_row])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "posthog.temporal.session_replay.replay_count_metrics.activities.get_client",
        return_value=mock_client,
    ):
        from posthog.temporal.session_replay.replay_count_metrics.activities import collect_replay_count_metrics

        await collect_replay_count_metrics(ReplayCountMetricsInput())


@pytest.mark.asyncio
async def test_activity_raises_on_empty_result():
    mock_client = AsyncMock()
    mock_client.read_query_as_jsonl = AsyncMock(return_value=[])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "posthog.temporal.session_replay.replay_count_metrics.activities.get_client",
            return_value=mock_client,
        ),
        pytest.raises(RuntimeError, match="ClickHouse returned empty result"),
    ):
        from posthog.temporal.session_replay.replay_count_metrics.activities import collect_replay_count_metrics

        await collect_replay_count_metrics(ReplayCountMetricsInput())
