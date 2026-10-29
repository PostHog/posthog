import asyncio
from functools import partial

import pytest
from unittest.mock import AsyncMock, Mock, patch

from temporalio.worker import Worker

from posthog.temporal.common.worker import ManagedWorker


@pytest.mark.asyncio
async def test_shutdown_drains_both_queues_before_stopping_shared_resources():
    workers = [Mock(spec=Worker, is_shutdown=False) for _ in range(2)]
    shutdown_started = [asyncio.Event(), asyncio.Event()]
    drained = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]

    async def shutdown(index):
        shutdown_started[index].set()
        await release[index].wait()
        workers[index].is_shutdown = True
        drained[index].set()

    workers[0].shutdown = AsyncMock(side_effect=partial(shutdown, 0))
    workers[1].shutdown = AsyncMock(side_effect=partial(shutdown, 1))
    metrics = Mock(start=AsyncMock(), stop=AsyncMock())
    managed = ManagedWorker(worker=workers[0], activity_workers=(workers[1],), metrics_server=metrics)

    with patch("posthog.temporal.common.worker.shutdown_asyncify_executor") as shutdown_executor:
        task = asyncio.create_task(managed.shutdown())
        try:
            async with asyncio.timeout(10):
                await asyncio.gather(*(event.wait() for event in shutdown_started))
                release[0].set()
                await drained[0].wait()
                assert not managed.is_shutdown()
                metrics.stop.assert_not_awaited()
                shutdown_executor.assert_not_called()
                release[1].set()
                await task
        finally:
            for event in release:
                event.set()
            await task
        assert managed.is_shutdown()
        metrics.stop.assert_awaited_once()
        shutdown_executor.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_worker", [0, 1])
async def test_worker_failure_stops_the_other_queue(failed_worker):
    workers = [Mock(spec=Worker), Mock(spec=Worker)]
    started = [asyncio.Event(), asyncio.Event()]
    stopped = [asyncio.Event(), asyncio.Event()]

    async def run(index):
        started[index].set()
        try:
            await started[1 - index].wait()
            if index == failed_worker:
                raise RuntimeError("poller failed")
            await asyncio.Event().wait()
        finally:
            stopped[index].set()

    workers[0].run = AsyncMock(side_effect=partial(run, 0))
    workers[1].run = AsyncMock(side_effect=partial(run, 1))
    managed = ManagedWorker(worker=workers[0], activity_workers=(workers[1],))

    async with asyncio.timeout(10):
        with pytest.raises(ExceptionGroup, match="unhandled errors in a TaskGroup") as exc:
            await managed.run()
    assert len(exc.value.exceptions) == 1
    assert str(exc.value.exceptions[0]) == "poller failed"
    assert all(event.is_set() for event in stopped)
