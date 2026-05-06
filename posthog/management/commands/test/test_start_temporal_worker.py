from unittest.mock import AsyncMock, patch

from django.core.management import call_command
from django.test import override_settings


class FakeManagedWorker:
    metrics_server = None

    def __init__(self) -> None:
        self.run = AsyncMock()
        self.shutdown = AsyncMock()

    def is_shutdown(self) -> bool:
        return False


def test_start_temporal_worker_starts_single_worker_for_task_queue() -> None:
    worker = FakeManagedWorker()
    workflows = {"single": {"workflow"}}
    activities = {"single": {"activity"}}

    with (
        patch("posthog.management.commands.start_temporal_worker.WORKFLOWS_DICT", workflows),
        patch("posthog.management.commands.start_temporal_worker.ACTIVITIES_DICT", activities),
        patch(
            "posthog.management.commands.start_temporal_worker.create_worker", new=AsyncMock(return_value=worker)
        ) as create_worker,
    ):
        call_command("start_temporal_worker", "--task-queue=single")

    assert create_worker.await_count == 1
    assert create_worker.await_args.kwargs["task_queue"] == "single"
    assert create_worker.await_args.kwargs["workflows"] == ["workflow"]
    assert create_worker.await_args.kwargs["activities"] == ["activity"]
    assert worker.run.await_count == 1


@override_settings(TEMPORAL_TASK_QUEUES="a,b,c")
def test_start_temporal_worker_starts_worker_for_each_configured_task_queue() -> None:
    workers = [FakeManagedWorker(), FakeManagedWorker(), FakeManagedWorker()]
    workflows = {
        "a": {"workflow-a"},
        "b": {"workflow-b"},
        "c": {"workflow-c"},
    }
    activities = {
        "a": {"activity-a"},
        "b": {"activity-b"},
        "c": {"activity-c"},
    }

    with (
        patch("posthog.management.commands.start_temporal_worker.WORKFLOWS_DICT", workflows),
        patch("posthog.management.commands.start_temporal_worker.ACTIVITIES_DICT", activities),
        patch(
            "posthog.management.commands.start_temporal_worker.create_worker",
            new=AsyncMock(side_effect=workers),
        ) as create_worker,
    ):
        call_command("start_temporal_worker")

    assert create_worker.await_count == 3
    for call, queue in zip(create_worker.await_args_list, ("a", "b", "c")):
        assert call.kwargs["task_queue"] == queue
        assert call.kwargs["workflows"] == [f"workflow-{queue}"]
        assert call.kwargs["activities"] == [f"activity-{queue}"]

    for worker in workers:
        assert worker.run.await_count == 1


@override_settings(TEMPORAL_TASK_QUEUE="fallback", TEMPORAL_TASK_QUEUES="")
def test_start_temporal_worker_falls_back_to_single_task_queue_when_task_queues_empty() -> None:
    worker = FakeManagedWorker()
    workflows = {"fallback": {"workflow"}}
    activities = {"fallback": {"activity"}}

    with (
        patch("posthog.management.commands.start_temporal_worker.WORKFLOWS_DICT", workflows),
        patch("posthog.management.commands.start_temporal_worker.ACTIVITIES_DICT", activities),
        patch(
            "posthog.management.commands.start_temporal_worker.create_worker", new=AsyncMock(return_value=worker)
        ) as create_worker,
    ):
        call_command("start_temporal_worker")

    assert create_worker.await_count == 1
    assert create_worker.await_args.kwargs["task_queue"] == "fallback"
    assert worker.run.await_count == 1
