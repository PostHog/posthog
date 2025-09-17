import enum
import json
import time
import asyncio
import datetime as dt
import threading
import dataclasses

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.shutdown import ShutdownMonitor


class WaitMode(enum.StrEnum):
    SYNC = "sync"
    ASYNC = "async"


@dataclasses.dataclass
class WaitInputs:
    wait_for: int | float | None
    raise_on_shutdown: bool = True
    mode: WaitMode = WaitMode.ASYNC
    heartbeat_timeout_seconds: int = 10
    start_to_close_timeout_seconds: int = 60
    maximum_attempts: int = 1


@dataclasses.dataclass
class WaitInputsActivity:
    wait_for: int | float | None
    raise_on_shutdown: bool = True


class Waiter:
    def __init__(self):
        self.is_waiting = asyncio.Event()
        self.is_waiting_sync = threading.Event()
        self.heartbeater: Heartbeater | None = None
        self.heartbeater_sync: HeartbeaterSync | None = None
        self.shutdown_monitor: ShutdownMonitor | None = None

    @activity.defn
    async def wait_for_activity(self, inputs: WaitInputsActivity) -> None:
        """A test activity that simply waits."""
        elapsed = 0.0
        loop = asyncio.get_running_loop()
        start = loop.time()
        self.shutdown_monitor = ShutdownMonitor()
        self.heartbeater = Heartbeater()

        self.is_waiting.set()
        await asyncio.sleep(0)

        async with self.heartbeater, self.shutdown_monitor:
            while True:
                elapsed = loop.time() - start

                if inputs.wait_for is not None and elapsed > inputs.wait_for:
                    return

                if inputs.raise_on_shutdown:
                    self.shutdown_monitor.raise_if_is_worker_shutdown()
                await asyncio.sleep(0)

    @activity.defn
    def wait_for_activity_sync(self, inputs: WaitInputsActivity) -> None:
        """A test activity that simply waits."""
        elapsed = 0.0
        start = time.monotonic()
        self.shutdown_monitor = ShutdownMonitor()
        self.heartbeater_sync = HeartbeaterSync()

        self.is_waiting_sync.set()

        with self.heartbeater_sync, self.shutdown_monitor:
            while True:
                elapsed = time.monotonic() - start

                if inputs.wait_for is not None and elapsed > inputs.wait_for:
                    return

                if inputs.raise_on_shutdown:
                    self.shutdown_monitor.raise_if_is_worker_shutdown()
                time.sleep(0.1)


@workflow.defn(name="wait")
class WaitWorkflow(PostHogWorkflow):
    """A test workflow that simply waits."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> WaitInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return WaitInputs(**loaded)

    @workflow.run
    async def run(self, inputs: WaitInputs) -> None:
        if inputs.mode == WaitMode.ASYNC:
            await workflow.execute_activity_method(
                Waiter.wait_for_activity,
                WaitInputsActivity(wait_for=inputs.wait_for, raise_on_shutdown=inputs.raise_on_shutdown),
                # Setting a timeout is required.
                start_to_close_timeout=dt.timedelta(seconds=inputs.start_to_close_timeout_seconds),
                heartbeat_timeout=dt.timedelta(seconds=inputs.heartbeat_timeout_seconds),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=1),
                    maximum_interval=dt.timedelta(seconds=1),
                    maximum_attempts=inputs.maximum_attempts,
                ),
            )
        elif inputs.mode == WaitMode.SYNC:
            await workflow.execute_activity_method(
                Waiter.wait_for_activity_sync,
                WaitInputsActivity(wait_for=inputs.wait_for, raise_on_shutdown=inputs.raise_on_shutdown),
                # Setting a timeout is required.
                start_to_close_timeout=dt.timedelta(seconds=inputs.start_to_close_timeout_seconds),
                heartbeat_timeout=dt.timedelta(seconds=inputs.heartbeat_timeout_seconds),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=1),
                    maximum_interval=dt.timedelta(seconds=1),
                    maximum_attempts=inputs.maximum_attempts,
                ),
            )


WAITER = Waiter()

WORKFLOWS = [WaitWorkflow]

ACTIVITIES = [WAITER.wait_for_activity, WAITER.wait_for_activity_sync]
