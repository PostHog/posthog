import json
import time
import uuid
import random
import asyncio
import datetime as dt
import operator
import dataclasses

import pytest
import freezegun

from django.conf import settings
from django.test import override_settings

import aiokafka
import structlog
import pytest_asyncio
import temporalio.testing
import temporalio.activity
import temporalio.workflow
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import (
    KAFKA_LOG_ENTRIES_TABLE_SQL,
    LOG_ENTRIES_TABLE,
    LOG_ENTRIES_TABLE_MV_SQL,
    TRUNCATE_LOG_ENTRIES_TABLE_SQL,
)
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES
from posthog.temporal.common.logger import BACKGROUND_LOGGER_TASKS, configure_logger, resolve_log_source

pytestmark = pytest.mark.asyncio


class LogCapture:
    """A test StructLog processor to capture logs."""

    def __init__(self, drop: bool = True):
        self.write_entries: list[str] = []
        self.produce_entries: list[str] = []
        self.drop = drop

    def __call__(self, logger, method_name, messages):
        """Append event_dict to entries and optionally drop the log."""
        if message := messages.get("write_message", None):
            self.write_entries.append(message)
        if message := messages.get("produce_message", None):
            self.produce_entries.append(message)

        if self.drop:
            raise structlog.DropEvent()
        else:
            return messages


@pytest.fixture()
def log_capture(request):
    """Return a LogCapture processor for inspection in tests."""
    try:
        drop = request.param
    except AttributeError:
        drop = True

    return LogCapture(drop)


class QueueCapture(asyncio.Queue[bytes]):
    """A test asyncio.Queue that captures items that we put into it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entries = []

    def put_nowait(self, item):
        """Append item to entries and delegate to asyncio.Queue."""
        self.entries.append(item)
        super().put_nowait(item)


@pytest_asyncio.fixture()
async def queue():
    """Return a QueueCapture queue for inspection in tests."""
    queue = QueueCapture(maxsize=0)

    yield queue


class CaptureKafkaProducer:
    """A test aiokafka.AIOKafkaProducer that captures calls to send_and_wait."""

    def __init__(self, *args, **kwargs):
        self.entries = []
        self._producer: None | aiokafka.AIOKafkaProducer = None

    @property
    def producer(self) -> aiokafka.AIOKafkaProducer:
        if self._producer is None:
            self._producer = aiokafka.AIOKafkaProducer(
                bootstrap_servers=[*settings.KAFKA_HOSTS, "localhost:9092"],
                security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
                acks="all",
                request_timeout_ms=1000000,
                api_version="2.5.0",
            )
        return self._producer

    async def send(self, topic, value=None, key=None, partition=None, timestamp_ms=None, headers=None):
        """Append an entry and delegate to aiokafka.AIOKafkaProducer."""

        self.entries.append(
            {
                "topic": topic,
                "value": value,
                "key": key,
                "partition": partition,
                "timestamp_ms": timestamp_ms,
                "headers": headers,
            }
        )
        return await self.producer.send(topic, value, key, partition, timestamp_ms, headers)

    async def start(self):
        await self.producer.start()

    async def stop(self):
        await self.producer.stop()

    async def flush(self):
        await self.producer.flush()

    @property
    def _closed(self):
        return self.producer._closed


@pytest_asyncio.fixture(scope="function")
async def producer(event_loop):
    """Yield a CaptureKafkaProducer to inspect entries captured.

    After usage, we ensure the producer was closed to avoid leaking/warnings.
    """
    producer = CaptureKafkaProducer(bootstrap_servers=settings.KAFKA_HOSTS, loop=event_loop)

    yield producer

    if producer._closed is False:
        await producer.stop()


@pytest_asyncio.fixture(autouse=True, scope="function")
async def configure_logger_auto(log_capture, queue, producer, event_loop):
    """Configure StructLog logging for testing.

    The extra parameters configured for testing are:
    * Add a LogCapture processor to capture logs.
    * Set the queue and producer to capture messages sent.
    * Do not cache logger to ensure each test starts clean.

    This fixture shadows the `configure_logger_auto` fixture so
    that we override the usual configuration with the specific parameters
    we need in these tests.
    """
    with override_settings(TEST=False, DEBUG=False):
        configure_logger(
            extra_processors=[log_capture],
            queue=queue,
            producer=producer,
            cache_logger_on_first_use=False,
            loop=event_loop,
        )

    yield

    for task in BACKGROUND_LOGGER_TASKS.values():
        # Clean up logger tasks to avoid leaking/warnings.
        task.cancel()

    await asyncio.wait(BACKGROUND_LOGGER_TASKS.values())


@pytest.fixture(autouse=True, scope="function")
def structlog_context():
    """Ensure a clean structlog context for tests."""
    ctx = structlog.contextvars.get_contextvars()
    structlog.contextvars.clear_contextvars()

    yield

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**ctx)


async def test_logger_context(log_capture, event_loop):
    """Test whether log messages contain the expected context.

    We expect a log message to contain:
    * The actual log message.
    * The log name passed to `get_logger`.
    * Context from global context (set by `bind_contextvars`).
    * Context from bound logger (set by `bind` method).
    * Keyword arguments passed to log method.
    * Additional context set by processors:
      * Log level.
      * Callsite parameters.
      * Timestamp
    * All of the above in both the sync and async versions of log method.

    We do **NOT** check for Temporal context in this test.
    """
    context_uuid = uuid.uuid4()
    structlog.contextvars.bind_contextvars(team_id=1, destination="Somewhere", uuid=context_uuid)
    logger = structlog.get_logger("test_logger_context")
    bound = logger.bind(test=True)

    bound.info("Hi! This is an %s log", "info", another=False)
    await bound.ainfo("Hi! This is an %s log", "info", another=False)

    assert len(log_capture.write_entries) == 2
    assert len(log_capture.produce_entries) == 0

    for entry in log_capture.write_entries:
        info_dict = json.loads(entry)

        assert info_dict.pop("msg") == "Hi! This is an info log"
        assert info_dict.pop("logger") == "test_logger_context"
        assert info_dict.pop("test") is True
        assert info_dict.pop("another") is False
        assert info_dict.pop("team_id") == 1
        assert info_dict.pop("destination") == "Somewhere"
        assert info_dict.pop("level") == "info"
        # Not deterministic, we just check it's there.
        assert info_dict.pop("timestamp") is not None
        assert info_dict.pop("func_name") == "test_logger_context"
        assert info_dict.pop("filename") == "test_logger.py"
        # Could change if test file changes, so we just check it's there.
        assert info_dict.pop("lineno") is not None
        assert info_dict.pop("uuid") == str(context_uuid)
        assert not info_dict


async def test_logger_renders_tracebacks(log_capture):
    """Test whether log messages contain tracebacks rendered properly.

    We check all possible ways of capturing exceptions in a log call:
    * Passing the exception object: `exc_info=e`.
    * Passing `True`: `exc_info=True`.
    * Using the `exception` log method.
    * Async versions of all of the above.
    """
    logger = structlog.get_logger("test_logger_renders_tracebacks")

    try:
        raise ValueError("Oh no!")
    except Exception as e:
        logger.error("Error", exc_info=e)  # noqa: TRY400
        logger.error("Error", exc_info=True)
        logger.exception("Error")

        await logger.aerror("Error", exc_info=e)
        await logger.aerror("Error", exc_info=True)
        await logger.aexception("Error")

    assert len(log_capture.write_entries) == 6
    assert len(log_capture.produce_entries) == 0

    for entry in log_capture.write_entries:
        entry_dict = json.loads(entry)

        assert "exception" in entry_dict
        assert isinstance(entry_dict["exception"], list)

        exceptions = entry_dict["exception"]

        assert len(exceptions) == 1

        exception = exceptions[0]

        assert exception["exc_type"] == "ValueError"
        assert exception["exc_value"] == "Oh no!"


async def test_logger_formats_positional_args(log_capture):
    """Test whether positional arguments are formatted in the message."""
    logger = structlog.get_logger("test_logger_formats_positional_args")

    logger.info("Hi! This is an %s log with %s %s", "info", "positional", "arguments")
    logger.error(
        "Hi! This is an %(level)s log with %(contains)s", {"level": "error", "contains": "named positional arguments"}
    )

    assert len(log_capture.write_entries) == 2

    info_entry, error_entry = log_capture.write_entries
    info_dict, error_dict = json.loads(info_entry), json.loads(error_entry)
    assert info_dict["msg"] == "Hi! This is an info log with positional arguments"
    assert error_dict["msg"] == "Hi! This is an error log with named positional arguments"


@dataclasses.dataclass
class ActivityInfo:
    """Provide our own Activity Info for testing."""

    activity_id: int
    activity_type: str
    attempt: int
    task_queue: str
    workflow_id: str
    workflow_namespace: str
    workflow_run_id: str
    workflow_type: str


@pytest.fixture
def activity_environment(request):
    """Return a testing temporal ActivityEnvironment."""
    env = temporalio.testing.ActivityEnvironment()
    env.info = request.param
    return env


ID = str(uuid.uuid4())

# Mocking information for different workflows
ACTIVITY_INFOS = [
    # Batch exports
    ActivityInfo(
        activity_id=random.randint(1, 10000),
        activity_type="test-activity",
        attempt=random.randint(1, 10000),
        task_queue="batch-exports-task-queue",
        workflow_id=f"{ID}-{dt.datetime.now(dt.UTC)}",
        workflow_namespace="prod-us",
        workflow_type="s3-export",
        workflow_run_id=str(uuid.uuid4()),
    ),
    ActivityInfo(
        activity_id=random.randint(1, 10000),
        activity_type="test-activity",
        attempt=random.randint(1, 10000),
        task_queue="batch-exports-task-queue",
        workflow_id=f"{ID}-Backfill-{dt.datetime.now(dt.UTC)}",
        workflow_namespace="prod-us",
        workflow_type="backfill-batch-export",
        workflow_run_id=str(uuid.uuid4()),
    ),
    # Data warehouse
    ActivityInfo(
        activity_id=random.randint(1, 10000),
        activity_type="test-activity",
        attempt=random.randint(1, 10000),
        task_queue="data-warehouse-task-queue",
        workflow_id=f"{ID}-{dt.datetime.now(dt.UTC)}",
        workflow_namespace="prod-us",
        workflow_type="external-data-job",
        workflow_run_id=str(uuid.uuid4()),
    ),
    ActivityInfo(
        activity_id=random.randint(1, 10000),
        activity_type="test-activity",
        attempt=random.randint(1, 10000),
        task_queue="data-warehouse-task-queue",
        workflow_id=f"{ID}-compaction",
        workflow_namespace="prod-us",
        workflow_type="deltalake-compaction-job",
        workflow_run_id=str(uuid.uuid4()),
    ),
    ActivityInfo(
        activity_id=random.randint(1, 10000),
        activity_type="test-activity",
        attempt=random.randint(1, 10000),
        task_queue="data-warehouse-task-queue",
        workflow_id=f"{ID}-{dt.datetime.now(dt.UTC)}",
        workflow_namespace="prod-us",
        workflow_type="data-modeling-run",
        workflow_run_id=str(uuid.uuid4()),
    ),
]


@pytest.mark.parametrize(
    "activity_environment",
    ACTIVITY_INFOS,
    indirect=True,
)
async def test_logger_binds_activity_context(
    log_capture,
    activity_environment,
):
    """Test whether our logger binds variables from a Temporal Activity."""

    def log_sync():
        """A simple function that just logs."""
        logger = structlog.get_logger()
        logger.info("Hi! This is an %s log from an activity", "info")

    async def log():
        """Async version that calls the simple function"""
        logger = structlog.get_logger()
        logger.info("Hi! This is an %s log from an activity", "info")
        await logger.ainfo("Hi! This is an %s log from an activity", "info")

    activities = map(temporalio.activity.defn, (log, log_sync))

    for activity in activities:
        if fut := activity_environment.run(activity):
            await fut
            assert len(log_capture.write_entries) == 2
        else:
            assert len(log_capture.write_entries) == 1

        for _ in range(len(log_capture.write_entries)):
            info_dict = json.loads(log_capture.write_entries.pop())
            assert info_dict["activity_id"] == activity_environment.info.activity_id
            assert info_dict["activity_type"] == activity_environment.info.activity_type
            assert info_dict["attempt"] == activity_environment.info.attempt
            assert info_dict["task_queue"] == activity_environment.info.task_queue
            assert info_dict["workflow_id"] == activity_environment.info.workflow_id
            assert info_dict["workflow_namespace"] == activity_environment.info.workflow_namespace
            assert info_dict["workflow_type"] == activity_environment.info.workflow_type
            assert info_dict["workflow_run_id"] == activity_environment.info.workflow_run_id


@freezegun.freeze_time("2023-11-02 10:00:00.123123")
@pytest.mark.parametrize(
    "activity_environment",
    ACTIVITY_INFOS,
    indirect=True,
)
@pytest.mark.parametrize("log_capture", [False], indirect=True)
async def test_logger_produces_to_log_queue_from_activity(activity_environment, queue):
    """Test whether our logger produces into a queue for async processing."""
    structlog.contextvars.bind_contextvars(team_id=2)

    def log_sync():
        """A simple function that logs with multiple loggers."""
        logger = structlog.get_logger("test_logger_produces_to_log_queue")
        produce_only = structlog.get_logger("test_produce_only", False, True)
        write_only = structlog.get_logger("test_write_only", True, False)

        logger.info("Hi! This is an external %s log from an activity", "info")
        produce_only.info("Hi! This is an external %s log from an activity", "info")
        write_only.info("Hi! This is an internal %s log from an activity", "info")

    async def log():
        """A simple async function that logs with multiple loggers."""
        logger = structlog.get_logger("test_logger_produces_to_log_queue")
        produce_only = structlog.get_logger("test_produce_only", False, True)
        write_only = structlog.get_logger("test_write_only", True, False)

        logger.info("Hi! This is an external %s log from an activity", "info")
        produce_only.info("Hi! This is an external %s log from an activity", "info")
        write_only.info("Hi! This is an internal %s log from an activity", "info")

        await logger.ainfo("Hi! This is an external %s log from an activity", "info")
        await produce_only.ainfo("Hi! This is an external %s log from an activity", "info")
        await write_only.ainfo("Hi! This is an internal %s log from an activity", "info")

    activities = map(temporalio.activity.defn, (log, log_sync))

    for activity in activities:
        if fut := activity_environment.run(activity):
            await fut

        while not queue.entries:
            # Let the loop run so messages have a chance to be inserted
            await asyncio.sleep(0)

        assert len(queue.entries) == 2 or len(queue.entries) == 4

        for _ in range(len(queue.entries)):
            message_dict = json.loads(queue.entries.pop().decode("utf-8"))
            log_source, log_source_id = resolve_log_source(
                activity_environment.info.workflow_type, activity_environment.info.workflow_id
            )

            assert message_dict["instance_id"] == activity_environment.info.workflow_run_id
            assert message_dict["level"] == "info"
            assert message_dict["log_source"] == log_source
            assert message_dict["log_source_id"] == log_source_id
            assert message_dict["message"] == "Hi! This is an external info log from an activity"
            assert message_dict["team_id"] == 2
            assert message_dict["timestamp"] == "2023-11-02 10:00:00.123123"


@pytest.fixture
def log_entries_table():
    """Manage log_entries table for testing."""
    sync_execute(KAFKA_LOG_ENTRIES_TABLE_SQL())
    sync_execute(LOG_ENTRIES_TABLE_MV_SQL)
    sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

    yield LOG_ENTRIES_TABLE

    sync_execute(f"DROP TABLE {LOG_ENTRIES_TABLE}_mv")
    sync_execute(f"DROP TABLE kafka_{LOG_ENTRIES_TABLE}")
    sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "activity_environment",
    ACTIVITY_INFOS,
    indirect=True,
)
@pytest.mark.parametrize("log_capture", [False], indirect=True)
async def test_logger_produces_to_kafka_from_activity(activity_environment, producer, queue, log_entries_table):
    """Test whether our log entries logger produces messages to Kafka.

    We also check if those messages are ingested into ClickHouse.

    Notice that we give each log message that is ingested into ClickHouse a different
    `team_id` parameter. This is because The `log_entries` table is a ReplacingMergeTree
    table that will remove duplicate log entries. So, since the table is ordered by a key
    that contains `team_id`, we give each log a different `team_id` to avoid automatic
    duplicate removal.
    """

    async def log():
        """A simple async function that logs with multiple loggers."""
        logger = structlog.get_logger("test_logger_produces_to_kafka")
        produce_only = structlog.get_logger("test_produce_only", False, True)
        write_only = structlog.get_logger("test_write_only", True, False)

        logger.info("Hi! This is an external %s log from an activity", "info", team_id=1)
        produce_only.info("Hi! This is an external %s log from an activity", "info", team_id=2)
        write_only.info("Hi! This is an internal %s log from an activity", "info")

        await logger.ainfo("Hi! This is an external %s log from an activity", "info", team_id=3)
        await produce_only.ainfo("Hi! This is an external %s log from an activity", "info", team_id=4)
        await write_only.ainfo("Hi! This is an internal %s log from an activity", "info", team_id=9999)

    def log_sync():
        """A simple function that logs with multiple loggers."""
        logger = structlog.get_logger("test_logger_produces_to_kafka")
        produce_only = structlog.get_logger("test_produce_only", False, True)
        write_only = structlog.get_logger("test_write_only", True, False)

        logger.info("Hi! This is an external %s log from an activity", "info", team_id=5)
        produce_only.info("Hi! This is an external %s log from an activity", "info", team_id=6)
        write_only.info("Hi! This is an internal %s log from an activity", "info", team_id=9999)

    activities = map(temporalio.activity.defn, (log, log_sync))

    team_id_producer_counter = 1
    team_id_row_counter = 1

    log_source, log_source_id = resolve_log_source(
        activity_environment.info.workflow_type, activity_environment.info.workflow_id
    )

    for activity in activities:
        with freezegun.freeze_time("2023-11-03 10:00:00.123123"):
            if fut := activity_environment.run(activity):
                await fut

        iterations = 0
        while not queue.entries:
            # Let the loop run so messages have a chance to be inserted
            await asyncio.sleep(1)

            iterations += 1
            if iterations > 10:
                raise TimeoutError("Timedout waiting for logs")

        assert len(queue.entries) == 2 or len(queue.entries) == 4

        await queue.join()
        queue.entries = []

        entries_captured = len(producer.entries)
        assert entries_captured == 2 or entries_captured == 4

        for _ in range(len(producer.entries)):
            entry = producer.entries.pop(0)

            assert entry["topic"] == KAFKA_LOG_ENTRIES
            assert entry["key"] is None
            assert entry["partition"] is None
            assert entry["timestamp_ms"] is None
            assert entry["headers"] is None

            log_dict = json.loads(entry["value"].decode("utf-8"))

            assert log_dict["instance_id"] == activity_environment.info.workflow_run_id
            assert log_dict["level"] == "info"
            assert log_dict["log_source"] == log_source
            assert log_dict["log_source_id"] == log_source_id
            assert log_dict["message"] == "Hi! This is an external info log from an activity"
            assert log_dict["team_id"] == team_id_producer_counter
            assert log_dict["timestamp"] == "2023-11-03 10:00:00.123123"

            team_id_producer_counter += 1

        await producer.flush()

        results = sync_execute(
            f"SELECT instance_id, level, log_source, log_source_id, message, team_id, timestamp FROM {log_entries_table} WHERE instance_id = '{activity_environment.info.workflow_run_id}' ORDER BY team_id ASC"
        )

        iterations = 0
        while not len(results) == entries_captured:
            # It may take a bit for CH to ingest.
            await asyncio.sleep(1)
            results = sync_execute(
                f"SELECT instance_id, level, log_source, log_source_id, message, team_id, timestamp FROM {log_entries_table} WHERE instance_id = '{activity_environment.info.workflow_run_id}' ORDER BY team_id ASC"
            )

            iterations += 1
            if iterations > 10:
                raise TimeoutError("Timedout waiting for logs")

        for row in results:
            assert row[0] == activity_environment.info.workflow_run_id
            assert row[1] == "info"
            assert row[2] == log_source
            assert row[3] == log_source_id
            assert row[4] == "Hi! This is an external info log from an activity"
            assert row[5] == team_id_row_counter
            assert row[6].isoformat() == "2023-11-03T10:00:00.123123+00:00"
            team_id_row_counter += 1

        sync_execute(f"TRUNCATE {log_entries_table}")


FIRST_WORKFLOW_TEAM_ID = 60


@temporalio.workflow.defn(name="external-data-job")
class TestWorkflow:
    @temporalio.workflow.run
    async def run(self):
        logger = structlog.get_logger("test_logger_produces_from_workflow")
        produce_only = structlog.get_logger("test_produce_only", False, True)
        write_only = structlog.get_logger("test_write_only", True, False)

        logger.info("Hi! This is an external %s log from a workflow", "info", team_id=FIRST_WORKFLOW_TEAM_ID)
        produce_only.info("Hi! This is an external %s log from a workflow", "info", team_id=FIRST_WORKFLOW_TEAM_ID + 1)
        write_only.info(
            "Hi! This is an internal %s log from a workflow. You should not see this.",
            "info",
            team_id=FIRST_WORKFLOW_TEAM_ID + 2,
        )


@freezegun.freeze_time("2023-11-02 10:00:00.123123")
@pytest.mark.parametrize("log_capture", [False], indirect=True)
async def test_logger_produces_to_log_queue_from_workflow(queue):
    """Test whether our logger produces into a queue for async processing."""

    workflow_id = str(uuid.uuid4())
    task_queue = "logging-test-task-queue"

    async with await WorkflowEnvironment.start_time_skipping() as workflow_environment:
        async with Worker(
            workflow_environment.client,
            task_queue=task_queue,
            workflows=[TestWorkflow],
            activities=[],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await workflow_environment.client.execute_workflow(
                TestWorkflow.run,
                id=workflow_id,
                task_queue=task_queue,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=5),
            )

    iterations = 0
    while not queue.entries:
        await asyncio.sleep(1)

        iterations += 1
        if iterations > 10:
            raise TimeoutError("Timedout waiting for logs")

    assert len(queue.entries) == 2
    entries = sorted([json.loads(entry.decode("utf-8")) for entry in queue.entries], key=operator.itemgetter("team_id"))

    for index, message_dict in enumerate(entries):
        log_source, log_source_id = resolve_log_source("external-data-job", workflow_id)

        assert message_dict["instance_id"]
        assert message_dict["level"] == "info"
        assert message_dict["log_source"] == log_source
        assert message_dict["log_source_id"] == log_source_id
        assert message_dict["message"] == "Hi! This is an external info log from a workflow"
        assert message_dict["team_id"] == FIRST_WORKFLOW_TEAM_ID + index
        assert message_dict["timestamp"] == "2023-11-02 10:00:00.123123"


@pytest.mark.django_db
@freezegun.freeze_time("2024-01-01 00:00:00")
@pytest.mark.parametrize("log_capture", [False], indirect=True)
async def test_logger_produces_to_kafka_from_workflow(producer, queue, log_entries_table):
    """Test whether our log entries logger produces messages to Kafka.

    We also check if those messages are ingested into ClickHouse.

    Notice that we give each log message that is ingested into ClickHouse a different
    `team_id` parameter. This is because The `log_entries` table is a ReplacingMergeTree
    table that will remove duplicate log entries. So, since the table is ordered by a key
    that contains `team_id`, we give each log a different `team_id` to avoid automatic
    duplicate removal.
    """

    workflow_id = str(uuid.uuid4())
    task_queue = "logging-test-task-queue"

    async with await WorkflowEnvironment.start_time_skipping() as workflow_environment:
        async with Worker(
            workflow_environment.client,
            task_queue=task_queue,
            workflows=[TestWorkflow],
            activities=[],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await workflow_environment.client.execute_workflow(
                TestWorkflow.run,
                id=workflow_id,
                task_queue=task_queue,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=5),
            )

    iterations = 0
    while not queue.entries:
        # Let the loop run so messages have a chance to be inserted
        await asyncio.sleep(1)

        iterations += 1
        if iterations > 10:
            raise TimeoutError("Timedout waiting for logs")

    assert len(queue.entries) == 2

    await queue.join()
    queue.entries = []

    entries_captured = len(producer.entries)
    assert entries_captured == 2

    log_source, log_source_id = resolve_log_source("external-data-job", workflow_id)

    for i in range(entries_captured):
        entry = producer.entries.pop(0)

        assert entry["topic"] == KAFKA_LOG_ENTRIES
        assert entry["key"] is None
        assert entry["partition"] is None
        assert entry["timestamp_ms"] is None
        assert entry["headers"] is None

        log_dict = json.loads(entry["value"].decode("utf-8"))

        assert log_dict["instance_id"]
        assert log_dict["level"] == "info"
        assert log_dict["log_source"] == log_source
        assert log_dict["log_source_id"] == log_source_id
        assert log_dict["message"] == "Hi! This is an external info log from a workflow"
        assert log_dict["team_id"] == FIRST_WORKFLOW_TEAM_ID + i
        assert log_dict["timestamp"] == "2024-01-01 00:00:00.000000"

    await producer.flush()

    iterations = 0

    while True:
        # It may take a bit for CH to ingest.
        results = sync_execute(
            f"SELECT instance_id, level, log_source, log_source_id, message, team_id, timestamp FROM {log_entries_table} ORDER BY team_id ASC"
        )

        if len(results) == entries_captured:
            break
        else:
            time.sleep(1)

        iterations += 1
        if iterations > 10:
            raise TimeoutError("Timedout waiting for logs")

    for index, row in enumerate(results):
        assert row[0] == log_dict["instance_id"]
        assert row[1] == "info"
        assert row[2] == log_source
        assert row[3] == log_source_id
        assert row[4] == "Hi! This is an external info log from a workflow"
        assert row[5] == FIRST_WORKFLOW_TEAM_ID + index
        assert row[6].isoformat() == "2024-01-01T00:00:00+00:00"
