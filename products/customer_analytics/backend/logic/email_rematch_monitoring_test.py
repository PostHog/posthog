from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.customer_analytics.backend.logic.email_rematch_monitoring import (
    FLUSH_TIMEOUT_SECONDS,
    run_tracked_email_thread_rematch,
)

MODULE = "products.customer_analytics.backend.logic.email_rematch_monitoring"


class _RecordingClient:
    def __init__(self, steps: list[tuple[object, ...]], *, fail: bool = False) -> None:
        self.steps = steps
        self.fail = fail
        self.properties: list[dict[str, Any]] = []

    def capture(self, *, distinct_id: str, event: str, properties: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("capture unavailable")
        self.steps.append(("capture", properties["status"]))
        self.properties.append(properties)

    def flush(self, *, timeout_seconds: float | None) -> None:
        self.steps.append(("flush", timeout_seconds))


class TestRunTrackedEmailThreadRematch:
    def _run(self, get_client: Any, *, retries: int, run: Any) -> int:
        with (
            patch(f"{MODULE}.is_cloud", return_value=True),
            patch(f"{MODULE}._get_client", get_client),
        ):
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
        steps: list[tuple[object, ...]] = []
        client = _RecordingClient(steps)

        def run() -> int:
            steps.append(("run",))
            if error is not None:
                raise error()
            return 7

        if error is None:
            assert self._run(lambda: client, retries=retries, run=run) == 7
        else:
            with pytest.raises(error):
                self._run(lambda: client, retries=retries, run=run)

        flush = ("flush", FLUSH_TIMEOUT_SECONDS)
        assert steps == [("capture", "started"), flush, ("run",), ("capture", terminal_status), flush]
        terminal = client.properties[-1]
        assert terminal["attempt"] == retries + 1
        assert terminal.get("error_type") == (None if error is None else error.__name__)
        assert terminal.get("threads_processed") == (7 if error is None else None)

    @parameterized.expand([("capture_raises",), ("client_setup_raises",)])
    def test_telemetry_failure_does_not_stop_the_rematch(self, failure: str) -> None:
        steps: list[tuple[object, ...]] = []

        def get_client() -> _RecordingClient:
            if failure == "client_setup_raises":
                raise RuntimeError("consumer thread could not start")
            return _RecordingClient(steps, fail=True)

        def run() -> int:
            steps.append(("run",))
            return 3

        assert self._run(get_client, retries=0, run=run) == 3
        assert steps == [("run",)]
