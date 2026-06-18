import enum
import time
import typing
import asyncio
import datetime as dt
import threading
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager, suppress
from types import TracebackType

from django.db import connections

import structlog
import temporalio.worker
from asgiref.sync import sync_to_async
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker

LOGGER = structlog.get_logger()


async def _cancel_task(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


class WaitResult(enum.Enum):
    BOTH_DONE = (True, True)
    WORKER_DONE = (True, False)
    SHUTDOWN_SET = (False, True)


class Runner:
    def __init__(self) -> None:
        self._error: tuple[BaseException, TracebackType | None] | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def thread(self) -> threading.Thread:
        if not self._thread:
            raise ValueError("Runner is not running")
        return self._thread

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if not self._loop:
            raise ValueError("Runner is not running")
        return self._loop

    @property
    def shutdown_event(self) -> asyncio.Event:
        if not self._shutdown_event:
            raise ValueError("Runner is not running")
        return self._shutdown_event

    async def _wait_for_shutdown_signal(self) -> None:
        await self.shutdown_event.wait()

    def _record_error(self, exc: BaseException) -> None:
        if self._error is None:
            self._error = (exc, exc.__traceback__)

    def _reraise_worker_error(self) -> None:
        if self._error is not None:
            exc, tb = self._error
            raise exc.with_traceback(tb)

    def run_in_thread(self, worker: Worker, *, start_timeout: int | float = 30.0) -> None:
        loop_ready = threading.Event()

        def run():
            async def main() -> None:
                self._shutdown_event = asyncio.Event()
                loop_ready.set()

                wait_task = asyncio.create_task(self._wait_for_shutdown_signal())
                worker_task = asyncio.create_task(worker.run())

                done, pending = await asyncio.wait(
                    [wait_task, worker_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                result = WaitResult((worker_task in done, wait_task in done))

                match result:
                    case WaitResult.SHUTDOWN_SET:
                        await worker.shutdown()
                        await worker_task
                    case WaitResult.BOTH_DONE | WaitResult.WORKER_DONE:
                        # If we land here, the worker failed to start or otherwise exited
                        await _cancel_task(wait_task)

                        try:
                            await worker_task
                        except Exception as exc:
                            raise RuntimeError("Temporal test worker exited unexpectedly") from exc

                    case _:
                        typing.assert_never(result)

            try:
                with asyncio.Runner() as runner:
                    self._loop = runner.get_loop()
                    try:
                        runner.run(main())
                    finally:
                        # Shutdown connections in asgiref thread-sensitive executor thread, if any
                        # sync_to_async ORM code may have run.
                        try:
                            runner.run(asyncio.wait_for(sync_to_async(connections.close_all)(), timeout=10))
                        except (TimeoutError, RuntimeError):
                            LOGGER.exception("Could not fully clean up Temporal test worker DB connections")

            except BaseException as exc:
                self._record_error(exc)
                raise

            finally:
                # Additionally, close any db connections owned by this worker thread.
                # There shouldn't be any, but just being defensive.
                connections.close_all()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._thread = t

        if not loop_ready.wait(timeout=start_timeout):
            if self._error is not None:
                self._reraise_worker_error()
            raise TimeoutError(f"Temporal test worker loop did not start within {start_timeout:g}s")

        deadline = time.monotonic() + start_timeout

        while not worker.is_running:
            if self._error is not None:
                self._reraise_worker_error()

            if not t.is_alive():
                if self._error is not None:
                    self._reraise_worker_error()
                raise RuntimeError("Temporal test worker thread exited before it started running")

            if time.monotonic() >= deadline:
                try:
                    self.shutdown()
                except Exception:
                    LOGGER.exception("Failed to shut down Temporal test worker after startup timeout")

                raise TimeoutError(f"Temporal test worker did not start within {start_timeout:g}s")

            time.sleep(0.1)

    def shutdown(self, *, timeout: int | float = 60.0) -> None:
        try:
            self.loop.call_soon_threadsafe(self.shutdown_event.set)
        except RuntimeError:
            # Loop is already closed, worker thread may have failed.
            pass

        self.thread.join(timeout=timeout)

        if self.thread.is_alive():
            raise RuntimeError(f"Temporal test worker thread did not shut down within {timeout:g}s")

        self._reraise_worker_error()


@contextmanager
def start_test_worker(
    temporal: TemporalClient,
    *,
    task_queue: str,
    workflows: Sequence[type],
    activities: Sequence[Callable],
    start_timeout: int | float = 30,
    shutdown_timeout: int | float = 60,
) -> Generator[Worker]:
    worker = Worker(
        client=temporal,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,
        workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=dt.timedelta(seconds=5),
    )

    runner = Runner()
    runner.run_in_thread(worker, start_timeout=start_timeout)

    test_exc: BaseException | None = None

    try:
        yield worker
    except BaseException as exc:
        test_exc = exc
        raise

    finally:
        try:
            runner.shutdown(timeout=shutdown_timeout)
        except Exception:
            if test_exc is not None:
                LOGGER.exception("Worker shutdown failed while test was already failing")
            else:
                raise
