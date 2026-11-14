from collections.abc import Callable
from concurrent.futures import Future
from contextlib import nullcontext
from functools import partial
from types import SimpleNamespace
from typing import Any

import pytest

import dagster
from confluent_kafka import ConsumerGroupTopicPartitions, KafkaError, KafkaException, TopicPartition
from confluent_kafka.admin import OffsetSpec
from parameterized import parameterized

from posthog.dags.personhog_shadow_lane import (
    SHADOW_CONSUMER_DEPLOYMENT,
    SHADOW_CONSUMER_GROUP,
    SHADOW_KAFKA_BOOTSTRAP_ENV_VAR,
    SHADOW_PROCESSOR_DEPLOYMENT,
    ShadowLaneStartConfig,
    ShadowLaneStopConfig,
    _move_consumer_offsets,
    processor_ramp,
    shadow_kafka_admin,
    start_shadow_lane,
    stop_shadow_lane,
    wait_for_deployments,
)


class TestWaitForDeployments:
    @parameterized.expand(
        [
            ("all_settle", {"consumer": 2, "processor": 1}, 60, set()),
            ("deadline_passed", {"consumer": 0, "processor": 0}, 0, {"consumer", "processor"}),
        ]
    )
    def test_returns_what_is_still_pending(
        self, _name: str, settles_on_check: dict[str, int], timeout_seconds: int, expected_pending: set[str]
    ) -> None:
        checks: dict[str, int] = dict.fromkeys(settles_on_check, 0)

        def is_settled(deployment: str) -> bool:
            checks[deployment] += 1
            return 0 < settles_on_check[deployment] <= checks[deployment]

        pending = wait_for_deployments(
            settles_on_check, is_settled, timeout_seconds=timeout_seconds, sleep=lambda _seconds: None
        )
        assert pending == expected_pending


class TestProcessorRamp:
    @parameterized.expand(
        [
            ("from_zero", 0, 256, 64, [64, 128, 192, 256]),
            ("partial_last_step", 0, 150, 64, [64, 128, 150]),
            ("holds_at_current_before_stepping", 200, 512, 128, [200, 328, 456, 512]),
            ("target_below_one_step", 0, 8, 64, [8]),
            ("scale_down_is_direct", 512, 256, 64, [256]),
        ]
    )
    def test_steps(self, _name: str, current: int, target: int, step: int, expected: list[int]) -> None:
        assert processor_ramp(current, target, step) == expected


class _ScalingAppsApi:
    def __init__(self, ready_cap: int | None = None, processor_replicas: int = 0) -> None:
        self.replicas = {SHADOW_PROCESSOR_DEPLOYMENT: processor_replicas, SHADOW_CONSUMER_DEPLOYMENT: 0}
        self.ready_cap = ready_cap
        self.scales: list[tuple[str, int]] = []

    def read_namespaced_deployment(self, name: str, namespace: str) -> SimpleNamespace:
        desired = self.replicas[name]
        ready = desired if self.ready_cap is None else min(desired, self.ready_cap)
        return SimpleNamespace(spec=SimpleNamespace(replicas=desired), status=SimpleNamespace(ready_replicas=ready))

    def patch_namespaced_deployment_scale(self, name: str, namespace: str, body: dict) -> None:
        self.replicas[name] = body["spec"]["replicas"]
        self.scales.append((name, self.replicas[name]))


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def scaling_apps(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _ScalingAppsApi]:
    def install(**kwargs: int) -> _ScalingAppsApi:
        apps = _ScalingAppsApi(**kwargs)
        clock = _FakeClock()
        monkeypatch.setattr("posthog.dags.personhog_shadow_lane.apps_api", lambda: apps)
        monkeypatch.setattr("posthog.dags.personhog_shadow_lane.pushed_metrics_registry", lambda _job: nullcontext())
        monkeypatch.setattr("posthog.dags.personhog_shadow_lane.time", clock)
        monkeypatch.setattr(
            "posthog.dags.personhog_shadow_lane.wait_for_deployments",
            partial(wait_for_deployments, sleep=clock.sleep),
        )
        return apps

    return install


def test_start_steps_processors_up_before_any_consumer(scaling_apps: Callable[..., _ScalingAppsApi]) -> None:
    apps = scaling_apps()
    config = ShadowLaneStartConfig(processor_replicas=150, processor_step_replicas=64, consumer_replicas=4)

    start_shadow_lane(dagster.build_op_context(), config)

    assert apps.scales == [
        (SHADOW_PROCESSOR_DEPLOYMENT, 64),
        (SHADOW_PROCESSOR_DEPLOYMENT, 128),
        (SHADOW_PROCESSOR_DEPLOYMENT, 150),
        (SHADOW_CONSUMER_DEPLOYMENT, 4),
    ]


@pytest.mark.parametrize("processor_replicas", [0, 64], ids=["fresh_start", "retry_with_pods_still_pending"])
def test_start_leaves_consumers_down_while_a_processor_step_is_unready(
    scaling_apps: Callable[..., _ScalingAppsApi], processor_replicas: int
) -> None:
    apps = scaling_apps(ready_cap=0, processor_replicas=processor_replicas)
    config = ShadowLaneStartConfig(processor_replicas=150, consumer_replicas=4, ready_timeout_seconds=60)

    with pytest.raises(dagster.Failure, match="did not reach 64 ready replicas"):
        start_shadow_lane(dagster.build_op_context(), config)

    assert apps.scales == [(SHADOW_PROCESSOR_DEPLOYMENT, 64)]


class _StoppingAppsApi:
    """A deployment scaled to zero keeps one pod for `linger_polls` pod-count polls, as a draining pod does."""

    def __init__(self, linger_polls: int) -> None:
        self.replicas = {SHADOW_CONSUMER_DEPLOYMENT: 4, SHADOW_PROCESSOR_DEPLOYMENT: 150}
        self.linger = dict.fromkeys(self.replicas, 0)
        self.linger_polls = linger_polls
        self.scales: list[tuple[str, int]] = []
        self.consumer_pods_at_scale: list[int] = []

    def pods(self, name: str) -> int:
        if self.replicas[name] > 0:
            return self.replicas[name]
        return 1 if self.linger[name] > 0 else 0

    def pod_count(self, name: str) -> int:
        count = self.pods(name)
        if self.replicas[name] == 0 and self.linger[name] > 0:
            self.linger[name] -= 1
        return count

    def patch_namespaced_deployment_scale(self, name: str, namespace: str, body: dict) -> None:
        self.consumer_pods_at_scale.append(self.pods(SHADOW_CONSUMER_DEPLOYMENT))
        self.replicas[name] = body["spec"]["replicas"]
        self.linger[name] = self.linger_polls
        self.scales.append((name, self.replicas[name]))


@pytest.fixture
def stopping_apps(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _StoppingAppsApi]:
    def install(linger_polls: int) -> _StoppingAppsApi:
        apps = _StoppingAppsApi(linger_polls)
        clock = _FakeClock()
        monkeypatch.setattr("posthog.dags.personhog_shadow_lane.time", clock)
        monkeypatch.setattr("posthog.dags.personhog_shadow_lane.apps_api", lambda: apps)
        monkeypatch.setattr(
            "posthog.dags.personhog_shadow_lane.deployment_pod_count",
            lambda _apps, _namespace, name: apps.pod_count(name),
        )
        monkeypatch.setattr(
            "posthog.dags.personhog_shadow_lane.wait_for_deployments",
            partial(wait_for_deployments, sleep=clock.sleep),
        )
        return apps

    return install


def test_stop_scales_processors_only_after_the_consumer_pods_are_gone(
    stopping_apps: Callable[..., _StoppingAppsApi],
) -> None:
    apps = stopping_apps(linger_polls=2)

    # Each deployment drains in 20 s of polls, within its own 30 s budget; together they would exceed one.
    stop_shadow_lane(dagster.build_op_context(), ShadowLaneStopConfig(stop_timeout_seconds=30))

    assert apps.scales == [(SHADOW_CONSUMER_DEPLOYMENT, 0), (SHADOW_PROCESSOR_DEPLOYMENT, 0)]
    assert apps.consumer_pods_at_scale == [4, 0]


def test_stop_leaves_processors_up_while_a_consumer_pod_lingers(
    stopping_apps: Callable[..., _StoppingAppsApi],
) -> None:
    apps = stopping_apps(linger_polls=100)

    with pytest.raises(dagster.Failure, match="Pods still running"):
        stop_shadow_lane(dagster.build_op_context(), ShadowLaneStopConfig(stop_timeout_seconds=30))

    assert apps.scales == [(SHADOW_CONSUMER_DEPLOYMENT, 0)]


class _FakeAppsApi:
    def __init__(self, desired_replicas: int, replicas_by_deployment: dict[str, int] | None = None) -> None:
        self.desired_replicas = desired_replicas
        self.replicas_by_deployment = replicas_by_deployment or {}

    def read_namespaced_deployment(self, name: str, namespace: str) -> SimpleNamespace:
        replicas = self.replicas_by_deployment.get(name, self.desired_replicas)
        return SimpleNamespace(
            spec=SimpleNamespace(replicas=replicas, selector=SimpleNamespace(match_labels={"app": name}))
        )


class _NoPodsCoreApi:
    def list_namespaced_pod(self, namespace: str, label_selector: str) -> SimpleNamespace:
        return SimpleNamespace(items=[])


@pytest.fixture
def lane_without_consumers(monkeypatch: pytest.MonkeyPatch) -> _FakeAppsApi:
    monkeypatch.setattr("posthog.dags.personhog_shadow_lane.k8s_client.CoreV1Api", _NoPodsCoreApi)
    return _FakeAppsApi(desired_replicas=0, replicas_by_deployment={SHADOW_PROCESSOR_DEPLOYMENT: 8})


class _FakeKafkaAdmin:
    """Answers offset lookups from fixed tables: a partition with nothing after the time reports -1.

    The end offsets move to latest_after_time_lookup once the time lookup runs, as they do when
    messages arrive between the two reads.
    """

    def __init__(
        self,
        at_time: dict[int, int],
        latest: dict[int, int],
        refuse: bool = False,
        latest_after_time_lookup: dict[int, int] | None = None,
    ) -> None:
        self.at_time = at_time
        self.latest = latest
        self.latest_after_time_lookup = latest_after_time_lookup
        self.refuse = refuse
        self.altered: list[tuple[str, list[tuple[int, int]]]] = []

    def list_topics(self, topic: str, timeout: float) -> Any:
        return SimpleNamespace(
            topics={topic: SimpleNamespace(partitions=dict.fromkeys(self.at_time), error=None)},
        )

    def list_offsets(self, topic_partition_offsets: dict[TopicPartition, Any], **_kwargs: Any) -> dict[Any, Future]:
        futures: dict[Any, Future] = {}
        is_latest = all(isinstance(spec, type(OffsetSpec.latest())) for spec in topic_partition_offsets.values())
        table = self.latest if is_latest else self.at_time
        for topic_partition in topic_partition_offsets:
            future: Future = Future()
            future.set_result(SimpleNamespace(offset=table[topic_partition.partition]))
            futures[topic_partition] = future
        if not is_latest and self.latest_after_time_lookup is not None:
            self.latest = self.latest_after_time_lookup
        return futures

    def alter_consumer_group_offsets(
        self, alter_consumer_group_offsets_request: list[ConsumerGroupTopicPartitions], **_kwargs: Any
    ) -> dict[str, Future]:
        futures: dict[str, Future] = {}
        for group in alter_consumer_group_offsets_request:
            future: Future = Future()
            if self.refuse:
                future.set_exception(KafkaException(KafkaError(KafkaError.UNKNOWN_MEMBER_ID)))  # type: ignore[attr-defined]
            else:
                self.altered.append(
                    (group.group_id, [(tp.partition, tp.offset) for tp in group.topic_partitions or []])
                )
                future.set_result(group)
            futures[group.group_id] = future
        return futures


def _no_admin() -> _FakeKafkaAdmin:
    raise AssertionError("the admin client must not be reached while the lane has pods")


def test_offset_move_refuses_while_lane_wants_pods() -> None:
    with pytest.raises(dagster.Failure, match="Run the stop job first"):
        _move_consumer_offsets(
            dagster.build_op_context(),
            ShadowLaneStartConfig(start_offsets_at_ms=1),
            _FakeAppsApi(desired_replicas=2),
            _no_admin,
        )


def test_offsets_move_to_the_time_and_past_the_end_to_the_end_before_the_lookup(
    lane_without_consumers: _FakeAppsApi,
) -> None:
    admin = _FakeKafkaAdmin(
        at_time={0: 10, 1: -1, 2: 30},
        latest={0: 50, 1: 99, 2: 50},
        latest_after_time_lookup={0: 51, 1: 100, 2: 51},
    )

    moved = _move_consumer_offsets(
        dagster.build_op_context(), ShadowLaneStartConfig(start_offsets_at_ms=1), lane_without_consumers, lambda: admin
    )

    assert moved == 3
    assert admin.altered == [(SHADOW_CONSUMER_GROUP, [(0, 10), (1, 99), (2, 30)])]


def test_offset_move_fails_when_kafka_refuses_it(lane_without_consumers: _FakeAppsApi) -> None:
    admin = _FakeKafkaAdmin(at_time={0: 10}, latest={0: 10}, refuse=True)
    with pytest.raises(dagster.Failure, match="Kafka refused to move"):
        _move_consumer_offsets(
            dagster.build_op_context(),
            ShadowLaneStartConfig(start_offsets_at_ms=1),
            lane_without_consumers,
            lambda: admin,
        )


def test_offset_reset_needs_the_bootstrap_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SHADOW_KAFKA_BOOTSTRAP_ENV_VAR, raising=False)
    with pytest.raises(dagster.Failure, match=SHADOW_KAFKA_BOOTSTRAP_ENV_VAR):
        shadow_kafka_admin()
