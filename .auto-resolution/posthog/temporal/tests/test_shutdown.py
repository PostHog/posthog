import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

import pytest_asyncio
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.tests.utils.workflow import Waiter, WaitInputs, WaitMode, WaitWorkflow


@pytest.mark.asyncio
async def test_shutdown_monitor_async(temporal_client: Client):
    """Test `ShutdownMonitor` behavior with a test workflow.

    The test workflow `WaitWorkflow` will wait for 30s, but before that, we will
    issue a cancellation to the worker running the Workflow.

    `ShutdownMonitor` should set the appropriate shutdown event. After re-starting
    the worker (simulating what would happen in production), the Workflow should
    fail with an exception raised from `ShutdownWorkflow`.
    """
    task_queue = "TEST-TASK-QUEUE"
    waiter = Waiter()
    inputs = WaitInputs(wait_for=30, mode=WaitMode.ASYNC)
    workflow_id = str(uuid.uuid4())

    worker = Worker(
        temporal_client,
        task_queue=task_queue,
        workflows=[WaitWorkflow],
        activities=[waiter.wait_for_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    worker_run_task = asyncio.create_task(worker.run())

    handle = await temporal_client.start_workflow(
        WaitWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=task_queue,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )

    _ = await waiter.is_waiting.wait()

    assert waiter.shutdown_monitor is not None

    wait_for_shutdown_task = asyncio.create_task(waiter.shutdown_monitor.wait_for_worker_shutdown())
    shutdown_task = asyncio.create_task(worker.shutdown())

    _ = await asyncio.wait([wait_for_shutdown_task], timeout=5)
    assert waiter.shutdown_monitor.is_worker_shutdown()

    _ = await asyncio.wait([shutdown_task, worker_run_task], timeout=5)
    # Need to start a new worker to pick-up the workflow again and set the failure.
    # Otherwise the workflow will never end.
    with pytest.raises(WorkflowFailureError) as exc_info:
        async with Worker(
            temporal_client,
            task_queue=task_queue,
            workflows=[WaitWorkflow],
            activities=[waiter.wait_for_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await handle.result()

    err = exc_info.value
    assert hasattr(err, "__cause__"), "Workflow failure missing cause"
    assert isinstance(err.__cause__, ActivityError)
    assert isinstance(err.__cause__.__cause__, ApplicationError)
    # We expect "WorkerShuttingDownError" to be raised, but depending on the timing
    # of threads, "WorkerShutdown" could be raised by temporal instead.
    assert err.__cause__.__cause__.type == "WorkerShuttingDownError" or err.__cause__.__cause__.type == "WorkerShutdown"


@pytest.fixture
def task_queue():
    return "TEST-TASK-QUEUE-SYNC"


@pytest.fixture
def waiter() -> Waiter:
    return Waiter()


@pytest_asyncio.fixture
async def worker(temporal_client: Client, waiter: Waiter, task_queue: str):
    with ThreadPoolExecutor(max_workers=50) as executor:
        worker = Worker(
            temporal_client,
            task_queue=task_queue,
            workflows=[WaitWorkflow],
            activities=[waiter.wait_for_activity_sync],
            activity_executor=executor,
            workflow_runner=UnsandboxedWorkflowRunner(),
            max_concurrent_activities=50,
        )
        worker_run_task = asyncio.create_task(worker.run())

        yield worker

        if not worker_run_task.done():
            _ = worker_run_task.cancel()

        _ = await asyncio.wait([worker_run_task])


@pytest.mark.asyncio
async def test_shutdown_monitor_sync(temporal_client: Client, task_queue: str, worker: Worker, waiter: Waiter):
    """Test `ShutdownMonitor` behavior with a test workflow.

    The test workflow `WaitWorkflow` will wait for 30s, but before that, we will
    issue a cancellation to the worker running the Workflow.

    `ShutdownMonitor` should set the appropriate shutdown event. After re-starting
    the worker (simulating what would happen in production), the Workflow should
    fail with an exception raised from `ShutdownWorkflow`.
    """
    inputs = WaitInputs(wait_for=30, mode=WaitMode.SYNC)
    workflow_id = str(uuid.uuid4())

    handle = await temporal_client.start_workflow(
        WaitWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=task_queue,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )

    _ = await asyncio.to_thread(waiter.is_waiting_sync.wait)
    shutdown_task = asyncio.create_task(worker.shutdown())

    _ = await asyncio.wait([shutdown_task], timeout=5)

    assert waiter.shutdown_monitor is not None
    assert waiter.shutdown_monitor.is_worker_shutdown()

    with ThreadPoolExecutor(max_workers=50) as executor:
        # Need to start a new worker to pick-up the workflow again and set the failure.
        # Otherwise the workflow will never end.
        with pytest.raises(WorkflowFailureError) as exc_info:
            async with Worker(
                temporal_client,
                task_queue=task_queue,
                workflows=[WaitWorkflow],
                activities=[waiter.wait_for_activity_sync],
                activity_executor=executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
                max_concurrent_activities=50,
            ):
                await handle.result()

        err = exc_info.value
        assert hasattr(err, "__cause__"), "Workflow failure missing cause"
        assert isinstance(err.__cause__, ActivityError)
        assert isinstance(err.__cause__.__cause__, ApplicationError)
        # We expect "WorkerShuttingDownError" to be raised, but depending on the timing
        # of threads, "WorkerShutdown" could be raised by temporal instead.
        assert (
            err.__cause__.__cause__.type == "WorkerShuttingDownError"
            or err.__cause__.__cause__.type == "WorkerShutdown"
        )
