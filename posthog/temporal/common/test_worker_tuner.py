import datetime as dt

import pytest
from unittest import mock

from temporalio.worker import ResourceBasedSlotConfig

from posthog.dataclasses import frozen
from posthog.temporal.common import worker

pytestmark = pytest.mark.asyncio


@frozen
class _WorkerMocks:
    worker_cls: mock.MagicMock
    create_resource_based: mock.MagicMock


async def _create_worker(**kwargs) -> _WorkerMocks:
    with (
        mock.patch.object(worker, "connect", new=mock.AsyncMock()),
        mock.patch.object(worker, "Worker") as worker_cls,
        mock.patch.object(worker, "CombinedMetricsServer"),
        mock.patch.object(worker, "configure_asyncify_executor"),
        mock.patch.object(worker.WorkerTuner, "create_resource_based") as create_resource_based,
    ):
        await worker.create_worker(
            host="localhost",
            port=7233,
            metrics_port=0,
            namespace="test",
            task_queue="test-queue",
            workflows=[],
            activities=[],
            max_concurrent_activities=7,
            **kwargs,
        )
    return _WorkerMocks(worker_cls=worker_cls, create_resource_based=create_resource_based)


async def test_create_worker_uses_fixed_slots_without_a_memory_target() -> None:
    mocks = await _create_worker(target_memory_usage=None)

    mocks.create_resource_based.assert_not_called()
    worker_kwargs = mocks.worker_cls.call_args.kwargs
    assert "tuner" not in worker_kwargs
    assert worker_kwargs["max_concurrent_activities"] == 7


@pytest.mark.parametrize("activity_ramp_throttle", [None, dt.timedelta(seconds=5)])
async def test_create_worker_uses_the_resource_tuner_with_a_memory_target(
    activity_ramp_throttle: dt.timedelta | None,
) -> None:
    mocks = await _create_worker(target_memory_usage=0.7, activity_ramp_throttle=activity_ramp_throttle)

    worker_kwargs = mocks.worker_cls.call_args.kwargs
    assert worker_kwargs["tuner"] is mocks.create_resource_based.return_value
    assert "max_concurrent_activities" not in worker_kwargs
    assert mocks.create_resource_based.call_args.kwargs["activity_config"] == ResourceBasedSlotConfig(
        maximum_slots=7, ramp_throttle=activity_ramp_throttle
    )
