import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.parametrize(
    "target_memory_usage,max_cached_workflows,expected",
    [
        # A deploy that sets the flag must see it reach the SDK; a silent no-op here
        # means the memory bound an operator configured never applies.
        (None, 25, 25),
        (0.6, 25, 25),
        (None, None, 1000),
    ],
)
@pytest.mark.asyncio
async def test_max_cached_workflows_reaches_the_sdk_worker(target_memory_usage, max_cached_workflows, expected):
    from posthog.temporal.common import worker as worker_module

    with (
        patch.object(worker_module, "connect", AsyncMock(return_value=MagicMock())),
        patch.object(worker_module, "Worker") as mock_worker,
        # Without this the test binds a real Prometheus socket on 0.0.0.0.
        patch.object(worker_module, "Runtime"),
    ):
        await worker_module.create_worker(
            host="localhost",
            port=7233,
            metrics_port=0,
            namespace="default",
            task_queue="test-queue",
            workflows=[],
            activities=[],
            target_memory_usage=target_memory_usage,
            max_cached_workflows=max_cached_workflows,
            enable_combined_metrics_server=False,
        )

    assert mock_worker.call_args.kwargs["max_cached_workflows"] == expected
