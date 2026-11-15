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
