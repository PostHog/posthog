import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.temporal.common.client import WorkerShuttingDownError, sync_connect


class TestSyncConnect:
    def test_interpreter_shutdown_runtimeerror_becomes_worker_shutting_down(self) -> None:
        # Guards the shutdown-race fix: async_to_sync's ThreadPoolExecutor raises this exact
        # RuntimeError when a web worker is torn down mid-request. sync_connect must translate it
        # into WorkerShuttingDownError so callers can skip reporting it as error-tracking noise.
        shutdown_error = RuntimeError("cannot schedule new futures after interpreter shutdown")
        with patch("posthog.temporal.common.client._sync_connect", side_effect=shutdown_error):
            with pytest.raises(WorkerShuttingDownError) as exc_info:
                sync_connect()

        assert exc_info.value.__cause__ is shutdown_error

    @parameterized.expand(
        [
            ("other_runtimeerror", RuntimeError("event loop is closed")),
            ("value_error", ValueError("boom")),
        ]
    )
    def test_unrelated_errors_propagate_unchanged(self, _name: str, error: Exception) -> None:
        with patch("posthog.temporal.common.client._sync_connect", side_effect=error):
            with pytest.raises(type(error)) as exc_info:
                sync_connect()

        assert not isinstance(exc_info.value, WorkerShuttingDownError)
        assert exc_info.value is error
