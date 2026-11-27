"""Operate the personhog shadow validation lane.

The shadow lane is a second consumer group on a production ingestion topic,
set in the lane's deployment. Its worker stores persons through a private
personhog stack only, whose database is a clone of the production persons
cluster, so the stack runs against production data and load.

This module holds the Kubernetes scaling plumbing and the start and stop jobs.

The Dagster service account needs get/patch on deployments and
deployments/scale plus list on pods in the lane namespace, and the lane's
ArgoCD Applications must ignore Deployment spec.replicas, or ArgoCD self-heal
reverts every scale these jobs apply. Both are charts-side prerequisites.
Moving the lane's offsets also needs the Kafka bootstrap servers of the
lane's cluster in PERSONHOG_SHADOW_KAFKA_BOOTSTRAP_SERVERS on the Dagster
deployment.
"""

import os
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future
from typing import Any, Protocol

import dagster
from confluent_kafka import ConsumerGroupTopicPartitions, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient, OffsetSpec
from kubernetes import (
    client as k8s_client,
    config as k8s_config,
)
from prometheus_client import CollectorRegistry, Gauge
from pydantic import Field

from posthog.dags.common import JobOwners
from posthog.metrics import pushed_metrics_registry

SHADOW_NAMESPACE = "ingestion-analytics-team2-shadow"
SHADOW_CONSUMER_DEPLOYMENT = "ingestion-analytics-team2-shadow-consumer"
SHADOW_PROCESSOR_DEPLOYMENT = "ingestion-analytics-team2-shadow-processor"
SHADOW_CONSUMER_GROUP = "ingestion-analytics-team2-shadow"
SHADOW_CONSUME_TOPIC = "ingestion-analytics-main-1024"
SHADOW_KAFKA_BOOTSTRAP_ENV_VAR = "PERSONHOG_SHADOW_KAFKA_BOOTSTRAP_SERVERS"
SHADOW_KAFKA_SECURITY_PROTOCOL_ENV_VAR = "PERSONHOG_SHADOW_KAFKA_SECURITY_PROTOCOL"

START_METRICS_JOB = "personhog_shadow_lane_start"


def _load_k8s_config() -> None:
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()


def apps_api() -> k8s_client.AppsV1Api:
    _load_k8s_config()
    return k8s_client.AppsV1Api()


def deployment_pod_count(apps: k8s_client.AppsV1Api, namespace: str, name: str) -> int:
    """Count the deployment's pods straight from the pod list.

    status.replicas lags a fresh scale and leaves out terminating pods, which
    can still write during their grace period, so the reset guard cannot rely
    on it.
    """
    deployment = apps.read_namespaced_deployment(name=name, namespace=namespace)
    if deployment.spec.replicas:
        return deployment.spec.replicas
    selector = ",".join(f"{key}={value}" for key, value in deployment.spec.selector.match_labels.items())
    pods = k8s_client.CoreV1Api().list_namespaced_pod(namespace=namespace, label_selector=selector)
    terminal_phases = {"Succeeded", "Failed"}
    return sum(1 for pod in pods.items if pod.status.phase not in terminal_phases)


def scale_deployment(apps: k8s_client.AppsV1Api, namespace: str, name: str, replicas: int) -> None:
    apps.patch_namespaced_deployment_scale(name=name, namespace=namespace, body={"spec": {"replicas": replicas}})


def deployment_ready_replicas(apps: k8s_client.AppsV1Api, namespace: str, name: str) -> int:
    deployment = apps.read_namespaced_deployment(name=name, namespace=namespace)
    return deployment.status.ready_replicas or 0


def wait_for_deployments(
    deployments: Iterable[str],
    is_settled: Callable[[str], bool],
    *,
    timeout_seconds: float,
    poll_seconds: float = 10,
    sleep: Callable[[float], None] = time.sleep,
) -> set[str]:
    """Poll each deployment until is_settled accepts it or the deadline passes.

    Returns the deployments still pending at the deadline, so the caller
    decides how to report them.
    """
    deadline = time.monotonic() + timeout_seconds
    pending = set(deployments)
    while pending and time.monotonic() < deadline:
        for deployment in sorted(pending):
            if is_settled(deployment):
                pending.discard(deployment)
        if pending:
            sleep(poll_seconds)
    return pending


class ShadowLaneStartConfig(dagster.Config):
    # Epoch ms the lane replays its topic from. Set it a few minutes before the clone point: a replayed
    # event is harmless, and a skipped one is lost to the run.
    start_offsets_at_ms: int | None = Field(default=None, gt=0)
    consumer_replicas: int = Field(default=4, gt=0, le=512)
    processor_replicas: int = Field(default=8, gt=0, le=512)
    processor_step_replicas: int = Field(default=64, gt=0, le=512)
    namespace: str = SHADOW_NAMESPACE
    consumer_deployment: str = SHADOW_CONSUMER_DEPLOYMENT
    processor_deployment: str = SHADOW_PROCESSOR_DEPLOYMENT
    # Applies to each processor step and to the consumers separately.
    ready_timeout_seconds: int = 600


def _require_consumers_stopped(
    config: ShadowLaneStartConfig, apps: k8s_client.AppsV1Api, option: str, reason: str
) -> None:
    # Only the consumers join the lane's consumer group. The processors take work from them over gRPC.
    pods = deployment_pod_count(apps, config.namespace, config.consumer_deployment)
    if pods > 0:
        raise dagster.Failure(
            description=(
                f"Deployment {config.consumer_deployment} still wants or has {pods} pod(s). "
                f"{reason} "
                f"Run the stop job first, then start with {option}."
            )
        )


class ConsumerGroupAdmin(Protocol):
    def list_topics(self, topic: str, timeout: float) -> Any: ...

    def list_offsets(self, topic_partition_offsets: dict[TopicPartition, Any], **kwargs: Any) -> dict[Any, Future]: ...

    def alter_consumer_group_offsets(
        self, alter_consumer_group_offsets_request: list[ConsumerGroupTopicPartitions], **kwargs: Any
    ) -> dict[str, Future]: ...


def shadow_kafka_admin() -> AdminClient:
    bootstrap_servers = os.environ.get(SHADOW_KAFKA_BOOTSTRAP_ENV_VAR)
    if not bootstrap_servers:
        raise dagster.Failure(
            description=(
                f"Environment variable {SHADOW_KAFKA_BOOTSTRAP_ENV_VAR} is not set on the Dagster deployment. "
                "It must hold the bootstrap servers of the Kafka cluster the shadow lane consumes from."
            )
        )
    return AdminClient(
        {
            "bootstrap.servers": bootstrap_servers,
            "security.protocol": os.environ.get(SHADOW_KAFKA_SECURITY_PROTOCOL_ENV_VAR, "SSL"),
            # The wheel's bundled OpenSSL does not read the system CA store unless told to probe for it.
            "ssl.ca.location": "probe",
        }
    )


def _resolved_offsets(futures: dict[Any, Future]) -> dict[int, int]:
    return {topic_partition.partition: future.result().offset for topic_partition, future in futures.items()}


def offsets_at(admin: ConsumerGroupAdmin, topic: str, timestamp_ms: int) -> list[TopicPartition]:
    """The first offset of each partition at or after timestamp_ms.

    A partition with nothing that recent gets its end offset, where Kafka reports none for the time.
    The end offsets are read before the time lookup, so a message that arrives between the two
    reads is consumed, not skipped.
    """
    metadata = admin.list_topics(topic=topic, timeout=30)
    topic_metadata = metadata.topics.get(topic)
    if topic_metadata is None or topic_metadata.error is not None:
        raise dagster.Failure(description=f"Topic {topic} is not readable: {getattr(topic_metadata, 'error', None)}")
    partitions = sorted(topic_metadata.partitions)
    ends = _resolved_offsets(
        admin.list_offsets(
            {TopicPartition(topic, partition): OffsetSpec.latest() for partition in partitions},
            request_timeout=30,
        )
    )
    offsets = _resolved_offsets(
        admin.list_offsets(
            {TopicPartition(topic, partition): OffsetSpec.for_timestamp(timestamp_ms) for partition in partitions},
            request_timeout=30,
        )
    )
    return [
        TopicPartition(topic, partition, offsets[partition] if offsets[partition] >= 0 else ends[partition])
        for partition in partitions
    ]


def _move_consumer_offsets(
    context: dagster.OpExecutionContext,
    config: ShadowLaneStartConfig,
    apps: k8s_client.AppsV1Api,
    admin_factory: Callable[[], ConsumerGroupAdmin] = shadow_kafka_admin,
) -> int:
    """Move the lane's consumer group to the offsets at config.start_offsets_at_ms. Returns the partitions moved."""
    assert config.start_offsets_at_ms is not None
    _require_consumers_stopped(
        config, apps, "start_offsets_at_ms", "Kafka refuses to move the offsets of a consumer group with members."
    )
    admin = admin_factory()
    offsets = offsets_at(admin, SHADOW_CONSUME_TOPIC, config.start_offsets_at_ms)
    future = admin.alter_consumer_group_offsets(
        [ConsumerGroupTopicPartitions(SHADOW_CONSUMER_GROUP, offsets)], request_timeout=30
    )[SHADOW_CONSUMER_GROUP]
    try:
        moved = future.result().topic_partitions
    except KafkaException as exception:
        raise dagster.Failure(
            description=(
                f"Kafka refused to move consumer group {SHADOW_CONSUMER_GROUP}: {exception.args[0]}. "
                "Wait for the lane's consumers to leave the group, then retry."
            )
        ) from exception
    failed = [topic_partition for topic_partition in moved if topic_partition.error is not None]
    if failed:
        raise dagster.Failure(
            description=f"Kafka did not move {len(failed)} partition(s) of {SHADOW_CONSUMER_GROUP}: {failed[:5]}"
        )
    context.log.info(
        f"Moved consumer group {SHADOW_CONSUMER_GROUP} on {SHADOW_CONSUME_TOPIC} to the offsets at "
        f"{config.start_offsets_at_ms} ms ({len(offsets)} partitions)"
    )
    return len(offsets)


def processor_ramp(current: int, target: int, step: int) -> list[int]:
    """Replica counts to scale the processors through, ending at target.

    A partly scaled deployment repeats its current count first, so a retried run waits for
    pods still pending from the last run before it adds more. A scale down goes straight to
    target, since removing pods needs no new nodes.
    """
    if target <= current:
        return [target]
    first = current if current > 0 else step
    return [*range(first, target, step), target]


def _scale_and_wait(
    context: dagster.OpExecutionContext,
    config: ShadowLaneStartConfig,
    apps: k8s_client.AppsV1Api,
    deployment: str,
    replicas: int,
) -> None:
    context.log.info(f"Scaling {config.namespace}/{deployment} to {replicas} replicas")
    scale_deployment(apps, config.namespace, deployment, replicas)

    def is_ready(name: str) -> bool:
        return deployment_ready_replicas(apps, config.namespace, name) >= replicas

    if wait_for_deployments([deployment], is_ready, timeout_seconds=config.ready_timeout_seconds):
        raise dagster.Failure(
            description=(
                f"{deployment} did not reach {replicas} ready replicas within {config.ready_timeout_seconds}s. "
                "The scale was applied; check the pods in the lane namespace."
            )
        )
    context.log.info(f"{deployment} is ready with {replicas} replica(s)")


def record_start_gauges(registry: CollectorRegistry, config: ShadowLaneStartConfig, completed_at: float) -> None:
    Gauge(
        "posthog_personhog_shadow_lane_start_last_success_timestamp_seconds",
        "Unix time when the shadow lane last started with every replica ready",
        ["namespace"],
        registry=registry,
    ).labels(namespace=config.namespace).set(completed_at)
    Gauge(
        "posthog_personhog_shadow_lane_start_offsets_at_seconds",
        "Unix time the last start moved the lane's consumer group to, 0 when it resumed from committed offsets",
        ["namespace"],
        registry=registry,
    ).labels(namespace=config.namespace).set((config.start_offsets_at_ms or 0) / 1000)
    replicas = Gauge(
        "posthog_personhog_shadow_lane_start_replicas",
        "Replicas the last start requested, by deployment",
        ["namespace", "deployment"],
        registry=registry,
    )
    replicas.labels(namespace=config.namespace, deployment=config.consumer_deployment).set(config.consumer_replicas)
    replicas.labels(namespace=config.namespace, deployment=config.processor_deployment).set(config.processor_replicas)


@dagster.op
def start_shadow_lane(context: dagster.OpExecutionContext, config: ShadowLaneStartConfig) -> None:
    apps = apps_api()
    if config.start_offsets_at_ms is not None:
        _move_consumer_offsets(context, config, apps)
    else:
        context.log.info("start_offsets_at_ms is unset, the lane resumes from its committed offsets")

    # Every processor is ready before any consumer starts. A consumer that starts first pins its keys to the
    # few processors already up, and those keys stay on them while they have work in flight.
    current = apps.read_namespaced_deployment(name=config.processor_deployment, namespace=config.namespace)
    for replicas in processor_ramp(
        current.spec.replicas or 0, config.processor_replicas, config.processor_step_replicas
    ):
        _scale_and_wait(context, config, apps, config.processor_deployment, replicas)
    _scale_and_wait(context, config, apps, config.consumer_deployment, config.consumer_replicas)

    with pushed_metrics_registry(f"{START_METRICS_JOB}_{config.namespace}") as registry:
        record_start_gauges(registry, config, time.time())

    context.add_output_metadata(
        {
            "start_offsets_at_ms": dagster.MetadataValue.int(config.start_offsets_at_ms or 0),
            "consumer_replicas": dagster.MetadataValue.int(config.consumer_replicas),
            "processor_replicas": dagster.MetadataValue.int(config.processor_replicas),
        }
    )


@dagster.job(tags={"owner": JobOwners.TEAM_INGESTION.value})
def personhog_shadow_lane_start_job():
    """Start the shadow lane consumers.

    Run with default config to resume consuming from the committed offsets.
    Set start_offsets_at_ms to replay the topic from that time instead,
    which refuses to run while the lane has consumer pods. Processors scale up in
    steps of processor_step_replicas, and the consumers start only once every
    processor is ready.
    """
    start_shadow_lane()


class ShadowLaneStopConfig(dagster.Config):
    namespace: str = SHADOW_NAMESPACE
    consumer_deployment: str = SHADOW_CONSUMER_DEPLOYMENT
    processor_deployment: str = SHADOW_PROCESSOR_DEPLOYMENT
    # Per deployment: the consumers get the full budget to drain before the processors scale.
    stop_timeout_seconds: int = 600


@dagster.op
def stop_shadow_lane(context: dagster.OpExecutionContext, config: ShadowLaneStopConfig) -> None:
    apps = apps_api()

    def is_stopped(deployment: str) -> bool:
        if deployment_pod_count(apps, config.namespace, deployment) > 0:
            return False
        context.log.info(f"{deployment} has no pods left")
        return True

    # Consumers first, and processors only once the consumers' pods are gone. A consumer drains its in-flight
    # batches before it exits, so the processors then hold no un-acked work. A processor scaled down while a
    # consumer still waits on it gets only its drain window to finish those batches, and fails what is left.
    for deployment in (config.consumer_deployment, config.processor_deployment):
        context.log.info(f"Scaling {config.namespace}/{deployment} to 0 replicas")
        scale_deployment(apps, config.namespace, deployment, 0)
        pending = wait_for_deployments([deployment], is_stopped, timeout_seconds=config.stop_timeout_seconds)
        if pending:
            raise dagster.Failure(
                description=f"Pods still running after {config.stop_timeout_seconds}s: {', '.join(sorted(pending))}"
            )


@dagster.job(tags={"owner": JobOwners.TEAM_INGESTION.value})
def personhog_shadow_lane_stop_job() -> None:
    """Stop the shadow lane: consumers first, then processors once the consumers' pods are gone."""
    stop_shadow_lane()
