import pytest
from unittest import mock

from django.test import override_settings

from temporalio.worker import PollerBehaviorAutoscaling

from posthog.temporal.common.worker import ActivityWorkerConfig, build_poller_autoscaling, create_worker


@pytest.mark.parametrize(
    "minimum,maximum,expected",
    [
        (None, None, None),
        (4, None, None),
        (None, 20, PollerBehaviorAutoscaling(minimum=1, maximum=20, initial=1)),
        (3, 20, PollerBehaviorAutoscaling(minimum=3, maximum=20, initial=3)),
        (5, 5, PollerBehaviorAutoscaling(minimum=5, maximum=5, initial=5)),
    ],
)
def test_build_poller_autoscaling(minimum, maximum, expected):
    assert build_poller_autoscaling("activity", minimum, maximum) == expected


@pytest.mark.parametrize(
    "minimum,maximum",
    [
        (None, 0),
        (0, 10),
        (-1, 10),
        (10, 5),
    ],
)
def test_build_poller_autoscaling_rejects_invalid_values(minimum, maximum):
    with pytest.raises(ValueError):
        build_poller_autoscaling("activity", minimum, maximum)


@pytest.mark.asyncio
@pytest.mark.parametrize("target_memory_usage", [None, 0.8])
@pytest.mark.parametrize(
    "poller_settings,expected_kwargs",
    [
        ({}, {}),
        (
            {"TEMPORAL_ACTIVITY_POLLER_AUTOSCALING_MAX": 30},
            {"activity_task_poller_behavior": PollerBehaviorAutoscaling(minimum=1, maximum=30, initial=1)},
        ),
        (
            {"TEMPORAL_ACTIVITY_POLLER_AUTOSCALING_MIN": 5, "TEMPORAL_ACTIVITY_POLLER_AUTOSCALING_MAX": 30},
            {"activity_task_poller_behavior": PollerBehaviorAutoscaling(minimum=5, maximum=30, initial=5)},
        ),
        (
            {"TEMPORAL_WORKFLOW_POLLER_AUTOSCALING_MIN": 2, "TEMPORAL_WORKFLOW_POLLER_AUTOSCALING_MAX": 10},
            {"workflow_task_poller_behavior": PollerBehaviorAutoscaling(minimum=2, maximum=10, initial=2)},
        ),
    ],
)
async def test_create_worker_passes_poller_behavior_only_when_configured(
    poller_settings, expected_kwargs, target_memory_usage
):
    with (
        override_settings(**poller_settings),
        mock.patch("posthog.temporal.common.worker.connect", new=mock.AsyncMock()) as connect,
        mock.patch("posthog.temporal.common.worker.Runtime"),
        mock.patch("posthog.temporal.common.worker.configure_asyncify_executor"),
        mock.patch("posthog.temporal.common.worker.WorkerTuner"),
        mock.patch("posthog.temporal.common.worker.Worker") as worker_cls,
    ):
        await create_worker(
            host="localhost",
            port=7233,
            metrics_port=0,
            namespace="default",
            task_queue="test-queue",
            workflows=[],
            activities=[],
            enable_combined_metrics_server=False,
            target_memory_usage=target_memory_usage,
            activity_worker_configs=[
                ActivityWorkerConfig(task_queue="aggregation-queue", activities=[], max_concurrent_activities=1)
            ],
        )

    primary, aggregation = worker_cls.call_args_list
    kwargs = primary.kwargs
    poller_kwargs = {k: v for k, v in kwargs.items() if k.endswith("poller_behavior")}
    assert poller_kwargs == expected_kwargs
    assert aggregation.args == primary.args
    assert aggregation.kwargs["task_queue"] == "aggregation-queue"
    assert aggregation.kwargs["max_concurrent_activities"] == 1
    assert "tuner" not in aggregation.kwargs
    connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_worker_rejects_invalid_poller_settings():
    with (
        override_settings(TEMPORAL_ACTIVITY_POLLER_AUTOSCALING_MIN=10, TEMPORAL_ACTIVITY_POLLER_AUTOSCALING_MAX=5),
        mock.patch("posthog.temporal.common.worker.connect", new=mock.AsyncMock()),
        mock.patch("posthog.temporal.common.worker.Runtime"),
        mock.patch("posthog.temporal.common.worker.configure_asyncify_executor"),
        mock.patch("posthog.temporal.common.worker.Worker"),
        pytest.raises(ValueError),
    ):
        await create_worker(
            host="localhost",
            port=7233,
            metrics_port=0,
            namespace="default",
            task_queue="test-queue",
            workflows=[],
            activities=[],
            enable_combined_metrics_server=False,
        )
