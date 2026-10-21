from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.customer_analytics.backend.logic.email_rematch_monitoring import run_tracked_email_thread_rematch

MODULE = "products.customer_analytics.backend.logic.email_rematch_monitoring"


class _RecordingCapture:
    def __init__(self, steps: list[tuple[str, ...]], *, fail: bool = False) -> None:
        self.steps = steps
        self.fail = fail
        self.properties: list[dict[str, Any]] = []

    def __call__(self, *, distinct_id: str, event: str, properties: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("capture unavailable")
        self.steps.append(("capture", properties["status"]))
        self.properties.append(properties)

    def flush(self) -> None:
        if self.fail:
            raise RuntimeError("capture unavailable")
        self.steps.append(("flush",))


class TestRunTrackedEmailThreadRematch:
    def _run(self, capture: _RecordingCapture, *, retries: int, run: Any) -> int:
        @contextmanager
        def scoped_capture() -> Iterator[_RecordingCapture]:
            yield capture

        with patch(f"{MODULE}.ph_scoped_capture", scoped_capture):
            return run_tracked_email_thread_rematch(
                team_id=42,
                rematch_type="threads",
                task_id="task-1",
                retries=retries,
                max_retries=3,
                run=run,
            )

    @parameterized.expand(
        [
            ("completed", 0, None, "completed"),
            ("first_error_retries", 0, ValueError, "retrying"),
            ("last_error_fails", 3, ValueError, "failed"),
            ("worker_shutdown", 1, SystemExit, "interrupted"),
        ]
    )
    def test_flushes_started_before_work_and_records_one_outcome(
        self, _name: str, retries: int, error: type[BaseException] | None, terminal_status: str
    ) -> None:
        steps: list[tuple[str, ...]] = []
        capture = _RecordingCapture(steps)

        def run() -> int:
            steps.append(("run",))
            if error is not None:
                raise error()
            return 7

        if error is None:
            assert self._run(capture, retries=retries, run=run) == 7
        else:
            with pytest.raises(error):
                self._run(capture, retries=retries, run=run)

        assert steps == [("capture", "started"), ("flush",), ("run",), ("capture", terminal_status)]
        terminal = capture.properties[-1]
        assert terminal["attempt"] == retries + 1
        assert terminal.get("error_type") == (None if error is None else error.__name__)
        assert terminal.get("threads_processed") == (7 if error is None else None)

    def test_capture_failure_does_not_stop_the_rematch(self) -> None:
        steps: list[tuple[str, ...]] = []

        def run() -> int:
            steps.append(("run",))
            return 3

        assert self._run(_RecordingCapture(steps, fail=True), retries=0, run=run) == 3
        assert steps == [("run",)]
