import json
import queue as sync_queue
from django.conf import settings
import kafka
import pytest
import structlog

from posthog.temporal.common.logger import bind_temporal_worker_logger_sync, configure_logger_sync


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


class QueueCapture(sync_queue.Queue):
    """A test queue.Queue that captures items that we put into it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entries = []

    def put_nowait(self, item):
        """Append item to entries and delegate to queue.Queue."""
        self.entries.append(item)
        super().put_nowait(item)


@pytest.fixture()
def queue():
    """Return a QueueCapture queue for inspection in tests."""
    queue = QueueCapture(maxsize=-1)

    yield queue


class CaptureKafkaProducer:
    """A test kafka.KafkaProducer that captures calls to send_and_wait."""

    def __init__(self, *args, **kwargs):
        self.entries = []
        self._producer: None | kafka.KafkaProducer = None

    @property
    def producer(self) -> kafka.KafkaProducer:
        if self._producer is None:
            self._producer = kafka.KafkaProducer(
                bootstrap_servers=[*settings.KAFKA_HOSTS, "localhost:9092"],
                security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
                acks="all",
                request_timeout_ms=1000000,
                api_version=(2, 5, 0),
            )
        return self._producer

    def send(self, topic, value=None, key=None, partition=None, timestamp_ms=None, headers=None):
        """Append an entry and delegate to kafka.KafkaProducer."""

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
        return self.producer.send(topic, value, key, partition, timestamp_ms, headers)

    def flush(self):
        self.producer.flush()

    @property
    def _closed(self):
        return self.producer._closed


@pytest.fixture
def producer():
    """Yield a CaptureKafkaProducer to inspect entries captured.

    After usage, we ensure the producer was closed to avoid leaking/warnings.
    """
    producer = CaptureKafkaProducer(bootstrap_servers=settings.KAFKA_HOSTS)

    yield producer


@pytest.fixture(autouse=True)
def configure(log_capture, queue, producer):
    """Configure StructLog logging for testing.

    The extra parameters configured for testing are:
    * Add a LogCapture processor to capture logs.
    * Set the queue and producer to capture messages sent.
    * Do not cache logger to ensure each test starts clean.
    """
    configure_logger_sync(
        extra_processors=[log_capture], queue=queue, producer=producer, cache_logger_on_first_use=False
    )

    yield


def test_logger_sync_binds_context(log_capture):
    """Test whether we can bind context variables."""
    logger = bind_temporal_worker_logger_sync(team_id=1, destination="Somewhere")

    logger.info("Hi! This is an info log")
    logger.error("Hi! This is an erro log")

    assert len(log_capture.entries) == 2

    info_entry, error_entry = log_capture.entries
    info_dict, error_dict = json.loads(info_entry), json.loads(error_entry)
    assert info_dict["team_id"] == 1
    assert info_dict["destination"] == "Somewhere"

    assert error_dict["team_id"] == 1
    assert error_dict["destination"] == "Somewhere"


def test_logger_sync_formats_positional_args(log_capture):
    """Test whether positional arguments are formatted in the message."""
    logger = bind_temporal_worker_logger_sync(team_id=1, destination="Somewhere")

    logger.info("Hi! This is an %s log", "info")
    logger.error("Hi! This is an %s log", "error")

    assert len(log_capture.entries) == 2

    info_entry, error_entry = log_capture.entries
    info_dict, error_dict = json.loads(info_entry), json.loads(error_entry)
    assert info_dict["msg"] == "Hi! This is an info log"
    assert error_dict["msg"] == "Hi! This is an error log"
