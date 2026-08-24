import json
import uuid
import asyncio
import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import pytest

from django.test import override_settings

import pytest_asyncio
import temporalio.testing

from posthog.temporal.common.logger import BACKGROUND_LOGGER_TASKS, configure_logger
from posthog.temporal.data_modeling.activities import (
    CreateDataModelingJobInputs,
    FailMaterializationInputs,
    SucceedMaterializationInputs,
    create_data_modeling_job_activity,
    fail_materialization_activity,
    succeed_materialization_activity,
)

if TYPE_CHECKING:
    from posthog.kafka_client.client import _AsyncKafkaProducer

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class QueueCapture(asyncio.Queue[bytes]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entries: list[bytes] = []

    def put_nowait(self, item: bytes) -> None:
        self.entries.append(item)
        super().put_nowait(item)


class NoopKafkaProducer:
    """Consumes produced log messages without a Kafka broker; capture happens at the queue."""

    async def produce(self, *, topic, data, key=None, value_serializer=None) -> None:
        return None

    async def flush(self, timeout=None) -> None:
        return None

    async def close(self) -> None:
        return None


@dataclasses.dataclass
class ActivityInfo:
    activity_id: str
    activity_type: str
    attempt: int
    task_queue: str
    workflow_id: str
    workflow_namespace: str
    workflow_run_id: str
    workflow_type: str


@pytest_asyncio.fixture
async def queue():
    return QueueCapture(maxsize=0)


@pytest_asyncio.fixture(autouse=True)
async def configure_produce_capture(queue):
    loop = asyncio.get_running_loop()
    with override_settings(TEST=False, DEBUG=False):
        configure_logger(
            queue=queue,
            producer=cast("_AsyncKafkaProducer", NoopKafkaProducer()),
            cache_logger_on_first_use=False,
            loop=loop,
            raise_on_producer_error=True,
        )

    yield

    for task in BACKGROUND_LOGGER_TASKS.values():
        task.cancel()
    if BACKGROUND_LOGGER_TASKS:
        await asyncio.wait(BACKGROUND_LOGGER_TASKS.values())


@pytest.fixture
def v2_activity_environment():
    env = temporalio.testing.ActivityEnvironment()
    env.info = ActivityInfo(  # type: ignore[assignment]
        activity_id=str(uuid.uuid4()),
        activity_type="test-activity",
        attempt=1,
        task_queue="data-modeling-task-queue",
        workflow_id=f"materialize-view-{uuid.uuid4()}-{uuid.uuid4()}",
        workflow_namespace="test",
        workflow_type="data-modeling-materialize-view",
        workflow_run_id=str(uuid.uuid4()),
    )
    return env


async def _wait_for_queue_entries(queue: QueueCapture, matches: Callable[[dict], bool] | None = None) -> None:
    # Produced lines reach the queue via `run_coroutine_threadsafe` from a thread-pool
    # executor, so a line can still be in flight after the activity returns. Wait for the
    # message we actually assert on — not just the first line to land — with real
    # wall-clock time, otherwise a generic log line can satisfy the wait before the routed
    # entry arrives and the assertion sees zero routed messages.
    for _ in range(200):
        if matches is None:
            if queue.entries:
                return
        elif any(matches(json.loads(entry.decode("utf-8"))) for entry in queue.entries):
            return
        await asyncio.sleep(0.01)
    raise TimeoutError("Timed out waiting for produced log messages")


@pytest.mark.parametrize("activity_case", ["create_job", "succeed", "fail"])
async def test_v2_activity_log_lines_are_routed_to_the_saved_query(
    activity_case, v2_activity_environment, queue, ateam, adag, anode, asaved_query, ajob
):
    if activity_case == "create_job":
        await v2_activity_environment.run(
            create_data_modeling_job_activity,
            CreateDataModelingJobInputs(team_id=ateam.pk, node_id=str(anode.id), dag_id=str(adag.id)),
        )
    elif activity_case == "succeed":
        await v2_activity_environment.run(
            succeed_materialization_activity,
            SucceedMaterializationInputs(
                team_id=ateam.pk,
                node_id=str(anode.id),
                dag_id=str(adag.id),
                job_id=str(ajob.id),
                row_count=1,
                duration_seconds=1.0,
            ),
        )
    else:
        await v2_activity_environment.run(
            fail_materialization_activity,
            FailMaterializationInputs(
                team_id=ateam.pk,
                node_id=str(anode.id),
                dag_id=str(adag.id),
                job_id=str(ajob.id),
                error="Something broke",
                update_node=False,
            ),
        )
    await _wait_for_queue_entries(queue, matches=lambda m: m.get("log_source") == "data_modeling_run")

    messages = [json.loads(entry.decode("utf-8")) for entry in queue.entries]
    routed_messages = [m for m in messages if m["log_source"] == "data_modeling_run"]
    assert len(routed_messages) >= 1
    for message in routed_messages:
        assert message["log_source_id"] == str(asaved_query.id)
        assert message["instance_id"] == v2_activity_environment.info.workflow_run_id
        assert message["team_id"] == ateam.pk


async def test_failure_logs_do_not_expose_clickhouse_hostnames(
    v2_activity_environment, queue, ateam, adag, anode, asaved_query, ajob
):
    await v2_activity_environment.run(
        fail_materialization_activity,
        FailMaterializationInputs(
            team_id=ateam.pk,
            node_id=str(anode.id),
            dag_id=str(adag.id),
            job_id=str(ajob.id),
            error="Code 241. Memory limit exceeded (from chi-posthog-data-0-0.svc.cluster.local:9000)",
            update_node=False,
        ),
    )
    await _wait_for_queue_entries(queue, matches=lambda m: bool(m.get("log_source")))

    routed_messages = [
        json.loads(entry.decode("utf-8")) for entry in queue.entries if json.loads(entry.decode("utf-8"))["log_source"]
    ]
    assert len(routed_messages) >= 1
    for message in routed_messages:
        assert "svc.cluster.local" not in message["message"]
    assert any("Memory limit exceeded" in message["message"] for message in routed_messages)
