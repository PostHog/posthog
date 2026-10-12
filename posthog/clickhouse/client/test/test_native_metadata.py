from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, BoundedSemaphore, Event, Lock

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.clickhouse.native_metadata import submit_native_metadata


class TestNativeMetadataCapacity(SimpleTestCase):
    def test_concurrent_first_use_initializes_one_executor_and_shares_capacity(self) -> None:
        constructor_started, second_constructor, release_constructor, release_work = Event(), Event(), Event(), Event()
        callers_ready = Barrier(8)
        constructor_count = 0
        count_lock = Lock()

        def blocked() -> str:
            if not release_work.wait(2):
                raise TimeoutError("test cleanup did not release native work")
            return "done"

        def submit() -> Future[str] | None:
            callers_ready.wait(timeout=1)
            return submit_native_metadata(blocked)

        def construct(*args: object, **kwargs: object) -> ThreadPoolExecutor:
            nonlocal constructor_count
            with count_lock:
                constructor_count += 1
                if constructor_count > 1:
                    second_constructor.set()
            constructor_started.set()
            if not release_constructor.wait(2):
                raise TimeoutError("test cleanup did not release executor construction")
            return executor

        with (
            ThreadPoolExecutor(max_workers=4) as executor,
            ThreadPoolExecutor(max_workers=8) as callers,
            patch("posthog.clickhouse.native_metadata._pool", None),
            patch("posthog.clickhouse.native_metadata._pool_lock", Lock()),
            patch("posthog.clickhouse.native_metadata._slots", BoundedSemaphore(4)),
            patch("posthog.clickhouse.native_metadata.ThreadPoolExecutor", side_effect=construct),
        ):
            requests = [callers.submit(submit) for _ in range(8)]
            try:
                self.assertTrue(constructor_started.wait(1))
                second_constructor.wait(0.1)
                self.assertEqual(constructor_count, 1)
                release_constructor.set()
                accepted = [job for request in requests if (job := request.result(timeout=1)) is not None]
                self.assertEqual(len(accepted), 4)
            finally:
                release_constructor.set()
                release_work.set()
            for job in accepted:
                self.assertEqual(job.result(timeout=1), "done")

    def test_running_and_queued_work_are_bounded_and_slots_are_reusable(self) -> None:
        release = Event()
        slots = BoundedSemaphore(2)

        def blocked() -> str:
            if not release.wait(2):
                raise TimeoutError("test cleanup did not release native work")
            return "done"

        with (
            ThreadPoolExecutor(max_workers=1) as executor,
            patch("posthog.clickhouse.native_metadata._native_metadata_executor", return_value=(executor, slots)),
        ):
            first = submit_native_metadata(blocked)
            queued = submit_native_metadata(blocked)
            try:
                self.assertIsNotNone(first)
                self.assertIsNotNone(queued)
                self.assertIsNone(submit_native_metadata(blocked))
                assert queued is not None
                self.assertTrue(queued.cancel())
                replacement = submit_native_metadata(lambda: "replacement")
                self.assertIsNotNone(replacement)
            finally:
                release.set()
            assert first is not None and replacement is not None
            self.assertEqual(first.result(timeout=1), "done")
            self.assertEqual(replacement.result(timeout=1), "replacement")
            reused = submit_native_metadata(lambda: "reused")
            assert reused is not None
            self.assertEqual(reused.result(timeout=1), "reused")

    def test_failed_submission_releases_capacity(self) -> None:
        slots = BoundedSemaphore(1)
        with (
            ThreadPoolExecutor(max_workers=1) as executor,
            patch("posthog.clickhouse.native_metadata._native_metadata_executor", return_value=(executor, slots)),
        ):
            with patch.object(executor, "submit", side_effect=RuntimeError("executor unavailable")):
                with self.assertRaisesRegex(RuntimeError, "executor unavailable"):
                    submit_native_metadata(lambda: None)
            retry = submit_native_metadata(lambda: "retry")
            assert retry is not None
            self.assertEqual(retry.result(timeout=1), "retry")
