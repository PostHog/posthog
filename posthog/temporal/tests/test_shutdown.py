import os
import uuid
import signal
import socket
import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor

import pytest

import pytest_asyncio
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.shutdown import ShutdownMonitor, ShutdownSignalListener, WorkerShuttingDownError
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

    # Generous bound: shutdown propagation is the thing under test and can take
    # longer than a few seconds on loaded CI runners.
    _ = await asyncio.wait([wait_for_shutdown_task], timeout=15)
    assert waiter.shutdown_monitor.is_worker_shutdown()
    assert waiter.shutdown_callback_ran.is_set()

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

    assert waiter.shutdown_monitor is not None
    # Wait on the monitor's own event: worker.shutdown() completing within a fixed
    # window is neither necessary nor sufficient for the sync event to be set, and
    # propagation can take longer than a few seconds on loaded CI runners.
    assert await asyncio.to_thread(waiter.shutdown_monitor.wait_for_worker_shutdown_sync, 15)

    _ = await asyncio.wait([shutdown_task], timeout=5)

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


@pytest.mark.asyncio
@pytest.mark.parametrize("wakeup_fd_full", [False, True])
async def test_shutdown_signal_listener_keeps_the_first_signal(wakeup_fd_full: bool):
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    read_sock, write_sock = socket.socketpair()
    write_sock.setblocking(False)
    previous_wakeup_fd = signal.set_wakeup_fd(write_sock.fileno()) if wakeup_fd_full else None
    try:
        if wakeup_fd_full:
            with contextlib.suppress(BlockingIOError):
                while True:
                    write_sock.send(b"\0" * 4096)

        listener = ShutdownSignalListener(poll_interval_seconds=0.01)
        listener.install()

        os.kill(os.getpid(), signal.SIGTERM)
        assert await asyncio.wait_for(listener.wait(), timeout=5) == signal.SIGTERM

        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.sleep(0.05)
        assert listener.received == signal.SIGTERM
    finally:
        if previous_wakeup_fd is not None:
            signal.set_wakeup_fd(previous_wakeup_fd)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        read_sock.close()
        write_sock.close()


class _GraceSleep:
    """Stands in for `asyncio.sleep` in the monitor, so a test decides when the grace ends."""

    def __init__(self) -> None:
        self.requested: list[float] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.requested.append(seconds)
        self.started.set()
        await self.release.wait()


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grace_seconds,finishes_in_grace,expected",
    [
        # Today's behaviour: the first check after the signal hands off.
        pytest.param(0.0, False, "handed_off_at_signal", id="no_grace_hands_off_at_once"),
        pytest.param(60.0, True, "finished", id="finishes_inside_the_grace"),
        pytest.param(60.0, False, "handed_off_after_grace", id="still_running_at_grace_end_hands_off"),
    ],
)
async def test_shutdown_grace_delays_what_every_check_sees(
    activity_environment, grace_seconds: float, finishes_in_grace: bool, expected: str
):
    sleep = _GraceSleep()
    callback_ran: list[bool] = []

    async def activity_body() -> str:
        async with ShutdownMonitor(grace_seconds=grace_seconds, sleep=sleep) as monitor:
            monitor.run_on_shutdown(lambda: callback_ran.append(True))
            wait_for_shutdown = asyncio.ensure_future(monitor.wait_for_worker_shutdown())
            await _settle()

            # Before the signal, no check sees a shutdown.
            monitor.raise_if_is_worker_shutdown()
            assert (monitor.is_worker_shutdown(), monitor.seconds_since_shutdown(), callback_ran) == (False, None, [])

            activity_environment.worker_shutdown()
            await _settle()
            try:
                monitor.raise_if_is_worker_shutdown()
            except WorkerShuttingDownError:
                assert wait_for_shutdown.done() and callback_ran == [True]
                return "handed_off_at_signal"

            assert sleep.requested == [grace_seconds]
            assert (monitor.is_worker_shutdown(), wait_for_shutdown.done(), callback_ran) == (False, False, [])
            if finishes_in_grace:
                return "finished"

            sleep.release.set()
            await asyncio.wait_for(wait_for_shutdown, timeout=5)
            assert callback_ran == [True]
            try:
                monitor.raise_if_is_worker_shutdown()
            except WorkerShuttingDownError:
                return "handed_off_after_grace"
            return "kept_running"

    assert await activity_environment.run(activity_body) == expected


@pytest.mark.parametrize(
    "grace_seconds,sync,error",
    [
        pytest.param(-1.0, False, "must not be negative", id="negative_grace"),
        # The thread monitor has no grace timer, so a grace there would never end.
        pytest.param(60.0, True, "needs the async monitor", id="grace_on_the_thread_monitor"),
    ],
)
def test_shutdown_grace_rejects_a_configuration_it_cannot_honour(grace_seconds: float, sync: bool, error: str):
    with pytest.raises(ValueError, match=error):
        monitor = ShutdownMonitor(grace_seconds=grace_seconds)
        if sync:
            monitor.start_sync()
