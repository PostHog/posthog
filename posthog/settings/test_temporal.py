import os
import importlib

import pytest
from unittest import mock

from posthog.settings import temporal


@pytest.mark.parametrize(
    "debug,single_task_queue,expected_shared,expected_isolated",
    [
        (False, False, "max-ai-task-queue", "alerts-platform-delivery-task-queue"),
        (False, True, "general-purpose-task-queue", "general-purpose-task-queue"),
        (True, False, "development-task-queue", "alerts-platform-delivery-task-queue"),
        (True, True, "development-task-queue", "alerts-platform-delivery-task-queue"),
    ],
)
def test_task_queue_collapse(
    debug: bool, single_task_queue: bool, expected_shared: str, expected_isolated: str
) -> None:
    with (
        mock.patch.object(temporal, "DEBUG", debug),
        mock.patch.object(temporal, "TEMPORAL_USE_SINGLE_TASK_QUEUE", single_task_queue),
        mock.patch.object(temporal, "default_task_queue", "general-purpose-task-queue"),
    ):
        assert temporal._set_temporal_task_queue("max-ai-task-queue") == expected_shared
        assert temporal._set_isolated_temporal_task_queue("alerts-platform-delivery-task-queue") == expected_isolated


def _sandbox_settings() -> dict[str, object]:
    return {name: getattr(temporal, name) for name in dir(temporal) if name.startswith("SANDBOX_")}


def test_sandbox_settings_ignore_environment_under_test() -> None:
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith("SANDBOX_")}
    try:
        with mock.patch.dict(os.environ, clean_env, clear=True):
            importlib.reload(temporal)
            expected = _sandbox_settings()

        polluted_env = {**clean_env, **dict.fromkeys(expected, "1")}
        with mock.patch.dict(os.environ, polluted_env, clear=True):
            importlib.reload(temporal)
            assert _sandbox_settings() == expected
    finally:
        importlib.reload(temporal)
