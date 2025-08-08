import asyncio
import dataclasses
import datetime as dt
import json
import random
import uuid

import aiokafka
import freezegun
import pytest
import pytest_asyncio
import structlog
import temporalio.activity
import temporalio.testing
from django.conf import settings
from django.test import override_settings

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import (
    KAFKA_LOG_ENTRIES_TABLE_SQL,
    LOG_ENTRIES_TABLE,
    LOG_ENTRIES_TABLE_MV_SQL,
    TRUNCATE_LOG_ENTRIES_TABLE_SQL,
)
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES
from posthog.temporal.common.logger import (
    BACKGROUND_LOGGER_TASKS,
    bind_contextvars,
    configure_logger,
    get_log_entries_logger,
    get_logger,
)

pytestmark = pytest.mark.asyncio


class LogCapture:
    """A test StructLog processor to capture logs."""

    def __init__(self):
        self.entries = []

    def __call__(self, logger, method_name, event_dict):
        """Append event_dict to entries and drop the log."""
        self.entries.append(event_dict)
        raise structlog.DropEvent()


@pytest.fixture()
def log_capture():
    """Return a LogCapture processor for inspection in tests."""
    return LogCapture()


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
    queue = QueueCapture(maxsize=-1)

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


@pytest_asyncio.fixture(autouse=True)
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
        # We override settings as otherwise we'll get console logs which
        # are not JSON
        configure_logger(
            extra_processors=[log_capture],
            queue=queue,
            producer=producer,
            cache_logger_on_first_use=False,
            loop=event_loop,
        )

    yield

    for task in BACKGROUND_LOGGER_TASKS:
        # Clean up logger tasks to avoid leaking/warnings.
        task.cancel()

    await asyncio.wait(BACKGROUND_LOGGER_TASKS)


async def test_logger_binds_context(log_capture):
    """Test whether we can bind context variables."""
    bind_contextvars(team_id=1, destination="Somewhere")
    logger = structlog.get_logger()
    logger.setLevel("INFO")

    logger.info("Hi! This is an info log")
    logger.error("Hi! This is an erro log")

    assert len(log_capture.entries) == 2

    info_entry, error_entry = log_capture.entries
    info_dict, error_dict = json.loads(info_entry), json.loads(error_entry)
    assert info_dict["team_id"] == 1
    assert info_dict["destination"] == "Somewhere"

    assert error_dict["team_id"] == 1
    assert error_dict["destination"] == "Somewhere"


async def test_logger_formats_positional_args(log_capture):
    """Test whether positional arguments are formatted in the message."""
    bind_contextvars(team_id=1, destination="Somewhere")
    logger = structlog.get_logger()
    logger.setLevel("INFO")

    logger.info("Hi! This is an %s log", "info")
    logger.error("Hi! This is an %s log", "error")

    assert len(log_capture.entries) == 2

    info_entry, error_entry = log_capture.entries
    info_dict, error_dict = json.loads(info_entry), json.loads(error_entry)
    assert info_dict["msg"] == "Hi! This is an info log"
    assert error_dict["msg"] == "Hi! This is an error log"


@dataclasses.dataclass
class ActivityInfo:
    """Provide our own Activity Info for testing."""

    workflow_id: str
    workflow_type: str
    workflow_run_id: str
    attempt: int


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
        workflow_id=f"{ID}-{dt.datetime.now(dt.UTC)}",
        workflow_type="s3-export",
        workflow_run_id=str(uuid.uuid4()),
        attempt=random.randint(1, 10000),
    ),
    ActivityInfo(
        workflow_id=f"{ID}-Backfill-{dt.datetime.now(dt.UTC)}",
        workflow_type="backfill-batch-export",
        workflow_run_id=str(uuid.uuid4()),
        attempt=random.randint(1, 10000),
    ),
    # Data warehouse
    ActivityInfo(
        workflow_id=f"{ID}-{dt.datetime.now(dt.UTC)}",
        workflow_type="external-data-job",
        workflow_run_id=str(uuid.uuid4()),
        attempt=random.randint(1, 10000),
    ),
    ActivityInfo(
        workflow_id=f"{ID}-compaction",
        workflow_type="deltalake-compaction-job",
        workflow_run_id=str(uuid.uuid4()),
        attempt=random.randint(1, 10000),
    ),
    ActivityInfo(
        workflow_id=f"{ID}-{dt.datetime.now(dt.UTC)}",
        workflow_type="data-modeling-run",
        workflow_run_id=str(uuid.uuid4()),
        attempt=random.randint(1, 10000),
    ),
]


def assert_log_source(log_source: str, workflow_type: str) -> None:
    """Assert the correct log source for given workflow type."""
    if workflow_type == "backfill-batch-export":
        assert log_source == "batch_exports_backfill"
    elif workflow_type == "external-data-job":
        assert log_source == "external_data_jobs"
    elif workflow_type == "deltalake-compaction-job":
        assert log_source == "deltalake_compaction_job"
    elif workflow_type == "data-modeling-run":
        assert log_source == "data_modeling_run"
    else:
        assert log_source == "batch_exports"


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
        bind_contextvars(team_id=1, destination="Somewhere")
        logger = structlog.get_logger()
        logger.setLevel("INFO")
        logger.info("Hi! This is an %s log from an activity", "info")

    async def log():
        """Async version that calls the simple function"""
        log_sync()

    activities = map(temporalio.activity.defn, (log, log_sync))

    for activity in activities:
        if fut := activity_environment.run(activity):
            await fut

        assert len(log_capture.entries) == 1

        info_dict = json.loads(log_capture.entries[0])
        assert info_dict["team_id"] == 1
        assert info_dict["destination"] == "Somewhere"
        assert info_dict["workflow_id"] == activity_environment.info.workflow_id
        assert info_dict["workflow_type"] == activity_environment.info.workflow_type
        assert info_dict["log_source_id"] == ID
        assert info_dict["workflow_run_id"] == activity_environment.info.workflow_run_id
        assert info_dict["attempt"] == activity_environment.info.attempt
        assert_log_source(info_dict["log_source"], activity_environment.info.workflow_type)

        log_capture.entries = []


@freezegun.freeze_time("2023-11-02 10:00:00.123123")
@pytest.mark.parametrize(
    "activity_environment",
    ACTIVITY_INFOS,
    indirect=True,
)
async def test_logger_puts_in_queue(activity_environment, queue):
    """Test whether our logger puts entries into a queue for async processing."""
    LOGGER = get_logger("test")
    EXTERNAL_LOGGER = get_log_entries_logger()

    def log_sync():
        """A simple function that just logs."""
        bind_contextvars(team_id=2, destination="Somewhere")
        logger = LOGGER.bind()
        external_logger = EXTERNAL_LOGGER.bind()

        external_logger.info("Hi! This is an external %s log from an activity", "info")
        logger.info("Hi! This is an internal %s log from an activity", "info")

    async def log():
        """Async version that calls the simple function"""
        log_sync()

    activities = map(temporalio.activity.defn, (log, log_sync))

    for activity in activities:
        if fut := activity_environment.run(activity):
            await fut

        while not queue.entries:
            # Let the loop run so messages have a chance to be inserted
            await asyncio.sleep(0)

        assert len(queue.entries) == 1
        message_dict = json.loads(queue.entries[0].decode("utf-8"))

        assert message_dict["instance_id"] == activity_environment.info.workflow_run_id
        assert message_dict["level"] == "info"
        assert message_dict["log_source_id"] == ID
        assert message_dict["message"] == "Hi! This is an external info log from an activity"
        assert message_dict["team_id"] == 2
        assert message_dict["timestamp"] == "2023-11-02 10:00:00.123123"
        assert_log_source(message_dict["log_source"], activity_environment.info.workflow_type)


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
async def test_logger_produces_to_kafka(activity_environment, producer, queue, log_entries_table):
    """Test whether our log entries logger produces messages to Kafka.

    We also check if those messages are ingested into ClickHouse.
    """
    LOGGER = get_logger("test")
    EXTERNAL_LOGGER = get_log_entries_logger()

    def log_sync():
        """A simple function that just logs."""
        bind_contextvars(team_id=3)
        logger = LOGGER.bind()
        external_logger = EXTERNAL_LOGGER.bind()

        external_logger.info("Hi! This is an external %s log from an activity", "info")
        logger.info("Hi! This is an internal %s log from an activity", "info")

    async def log():
        """Async version that calls the simple function"""
        log_sync()

    activities = map(temporalio.activity.defn, (log, log_sync))

    for activity in activities:
        with freezegun.freeze_time("2023-11-03 10:00:00.123123"):
            if fut := activity_environment.run(activity):
                await fut

        while not queue.entries:
            # Let the loop run so messages have a chance to be inserted
            await asyncio.sleep(0)

        assert len(queue.entries) == 1

        await queue.join()

        assert len(producer.entries) == 1
        assert producer.entries[0]["topic"] == KAFKA_LOG_ENTRIES
        assert producer.entries[0]["key"] is None
        assert producer.entries[0]["partition"] is None
        assert producer.entries[0]["timestamp_ms"] is None
        assert producer.entries[0]["headers"] is None

        log_dict = json.loads(producer.entries[0]["value"].decode("utf-8"))
        assert log_dict["instance_id"] == activity_environment.info.workflow_run_id
        assert log_dict["level"] == "info"
        assert log_dict["log_source_id"] == ID
        assert log_dict["message"] == "Hi! This is an external info log from an activity"
        assert log_dict["team_id"] == 3
        assert log_dict["timestamp"] == "2023-11-03 10:00:00.123123"
        assert_log_source(log_dict["log_source"], activity_environment.info.workflow_type)

        await producer.flush()

        results = sync_execute(
            f"SELECT instance_id, level, log_source, log_source_id, message, team_id, timestamp FROM {log_entries_table} WHERE instance_id = '{activity_environment.info.workflow_run_id}'"
        )

        iterations = 0
        while not results:
            # It may take a bit for CH to ingest.
            await asyncio.sleep(1)
            results = sync_execute(
                f"SELECT instance_id, level, log_source, log_source_id, message, team_id, timestamp FROM {log_entries_table} WHERE instance_id = '{activity_environment.info.workflow_run_id}'"
            )

            iterations += 1
            if iterations > 10:
                raise TimeoutError("Timedout waiting for logs")

        assert len(results) == 1

        row = results[0]
        assert row[0] == activity_environment.info.workflow_run_id
        assert row[1] == "info"
        assert row[3] == ID
        assert row[4] == "Hi! This is an external info log from an activity"
        assert row[5] == 3
        assert row[6].isoformat() == "2023-11-03T10:00:00.123123+00:00"
        assert_log_source(row[2], activity_environment.info.workflow_type)
