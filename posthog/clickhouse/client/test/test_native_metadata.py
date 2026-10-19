import sys
import json
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from threading import Barrier, BoundedSemaphore, Event, Lock
from time import monotonic

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.native_metadata import _run_metadata_process, submit_legacy_metadata, submit_native_metadata


def _set_event(event: Event, _future: Future) -> None:
    event.set()


class TestNativeMetadataCapacity(SimpleTestCase):
    @parameterized.expand([(True,), (False,)])
    def test_hung_children_are_reaped_and_all_cancellation_slots_recover(self, native: bool) -> None:
        started = Barrier(5)
        processes: list[subprocess.Popen] = []
        original_popen = subprocess.Popen
        # signal.pause simulates DNS/driver code that never returns, without a test sleep.
        program = "import json,signal,sys; job=json.load(sys.stdin); signal.pause() if job['hang'] else print(json.dumps({'result': True}))"

        def launch(_args, **kwargs):
            process = original_popen([sys.executable, "-c", program], **kwargs)
            processes.append(process)
            if len(processes) <= 4:
                started.wait(timeout=5)
            return process

        def run(payload: str, _deadline: float):
            return _run_metadata_process(payload, monotonic() + 1)

        submit = submit_native_metadata if native else submit_legacy_metadata
        released = [Event() for _ in range(4)]
        with (
            ThreadPoolExecutor(max_workers=4) as executor,
            patch("posthog.clickhouse.native_metadata._pools", {(native, False): (executor, BoundedSemaphore(4))}),
            patch("posthog.clickhouse.native_metadata.subprocess.Popen", side_effect=launch),
            patch("posthog.clickhouse.native_metadata._run_metadata_process", side_effect=run),
        ):
            futures = [submit({"hang": True}) for _ in range(4)]
            started.wait(timeout=5)
            self.assertIsNone(submit({"hang": False}))
            for future, done in zip(futures, released):
                assert future is not None
                future.add_done_callback(partial(_set_event, done))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=5)
                self.assertTrue(done.wait(1))
            self.assertTrue(all(process.poll() is not None for process in processes))
            replacement = submit({"hang": False})
            assert replacement is not None
            self.assertTrue(replacement.result(timeout=5))
            self.assertTrue(all(process.poll() is not None for process in processes))

    def test_stalled_poll_cannot_consume_either_clusters_cancellation_capacity(self) -> None:
        release, started = Event(), Event()

        def run(payload: str, _deadline: float):
            if json.loads(payload).get("poll"):
                started.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release poll")
            return True

        pools: dict[tuple[bool, bool], tuple[ThreadPoolExecutor, BoundedSemaphore]] = {}
        with (
            patch("posthog.clickhouse.native_metadata._pools", pools),
            patch("posthog.clickhouse.native_metadata._run_metadata_process", side_effect=run),
        ):
            try:
                poll = submit_legacy_metadata({"poll": True}, polling=True)
                self.assertTrue(started.wait(1))
                self.assertIsNone(submit_legacy_metadata({}, polling=True))
                for submit in (submit_legacy_metadata, submit_native_metadata):
                    cancellation = submit({})
                    assert cancellation is not None
                    self.assertTrue(cancellation.result(timeout=1))
            finally:
                release.set()
                for executor, _ in pools.values():
                    executor.shutdown()
            assert poll is not None
            self.assertTrue(poll.result())

    def test_concurrent_initialization_and_failed_submission_preserve_capacity(self) -> None:
        gate = Barrier(8)
        release = Event()
        pools: dict[tuple[bool, bool], tuple[ThreadPoolExecutor, BoundedSemaphore]] = {}

        def submit():
            gate.wait(timeout=2)
            return submit_native_metadata({})

        with (
            patch("posthog.clickhouse.native_metadata._pools", pools),
            patch("posthog.clickhouse.native_metadata._pool_lock", Lock()),
            patch("posthog.clickhouse.native_metadata._run_metadata_process", side_effect=lambda *_: release.wait(5)),
            ThreadPoolExecutor(max_workers=8) as callers,
        ):
            try:
                requests = [callers.submit(submit) for _ in range(8)]
                accepted = [future for request in requests if (future := request.result(timeout=3)) is not None]
                self.assertEqual(len(accepted), 4)
                self.assertEqual(len(pools), 1)
            finally:
                release.set()
                for executor, _ in pools.values():
                    executor.shutdown()
        executor, slots = pools[(True, False)]
        with patch("posthog.clickhouse.native_metadata._pools", pools):
            with self.assertRaises(RuntimeError):
                submit_native_metadata({})
            self.assertTrue(slots.acquire(blocking=False))
            slots.release()
