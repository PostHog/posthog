import dataclasses
import datetime as dt
import logging
import random
import string
import uuid
from unittest.mock import patch

import pytest
from freezegun import freeze_time
from temporalio import activity, workflow

from posthog.clickhouse.log_entries import (
    KAFKA_LOG_ENTRIES,
)
from posthog.temporal.workflows.batch_exports import (
    KafkaLoggingHandler,
    get_batch_exports_logger,
)


def test_kafka_logging_handler_produces_to_kafka(caplog):
    """Test a mocked call to Kafka produce from the KafkaLoggingHandler."""
    logger_name = "test-logger"
    logger = logging.getLogger(logger_name)
    handler = KafkaLoggingHandler(topic=KAFKA_LOG_ENTRIES)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    team_id = random.randint(1, 10000)
    batch_export_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    timestamp = "2023-09-21 00:01:01.000001"

    expected_tuples = []
    expected_kafka_produce_calls_kwargs = []

    with patch("posthog.kafka_client.client._KafkaProducer.produce") as produce:
        with caplog.at_level(logging.DEBUG):
            with freeze_time(timestamp):
                for level in (10, 20, 30, 40, 50):
                    random_message = "".join(random.choice(string.ascii_letters) for _ in range(30))

                    logger.log(
                        level,
                        random_message,
                        extra={
                            "team_id": team_id,
                            "batch_export_id": batch_export_id,
                            "workflow_run_id": run_id,
                        },
                    )

                    expected_tuples.append(
                        (
                            logger_name,
                            level,
                            random_message,
                        )
                    )
                    data = {
                        "message": random_message,
                        "team_id": team_id,
                        "batch_export_id": batch_export_id,
                        "run_id": run_id,
                        "timestamp": timestamp,
                        "level": logging.getLevelName(level),
                    }
                    expected_kafka_produce_calls_kwargs.append({"topic": KAFKA_LOG_ENTRIES, "data": data, "key": None})

        assert caplog.record_tuples == expected_tuples

        kafka_produce_calls_kwargs = [call.kwargs for call in produce.call_args_list]
        assert kafka_produce_calls_kwargs == expected_kafka_produce_calls_kwargs


@dataclasses.dataclass
class TestInputs:
    team_id: int
    data_interval_end: str | None = None
    interval: str = "hour"
    batch_export_id: str = ""


@dataclasses.dataclass
class TestInfo:
    workflow_id: str
    run_id: str
    workflow_run_id: str
    attempt: int


@pytest.mark.parametrize("context", [activity.__name__, workflow.__name__])
def test_batch_export_logger_adapter(context, caplog):
    """Test BatchExportLoggerAdapter sets the appropiate context variables."""
    team_id = random.randint(1, 10000)
    inputs = TestInputs(team_id=team_id)
    logger = get_batch_exports_logger(inputs=inputs)

    batch_export_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    attempt = random.randint(1, 10)
    info = TestInfo(
        workflow_id=f"{batch_export_id}-{dt.datetime.utcnow().isoformat()}",
        run_id=run_id,
        workflow_run_id=run_id,
        attempt=attempt,
    )

    with patch("posthog.kafka_client.client._KafkaProducer.produce"):
        with patch(context + ".info", return_value=info):
            for level in (10, 20, 30, 40, 50):
                logger.log(level, "test")

    records = caplog.get_records("call")
    assert all(record.team_id == team_id for record in records)
    assert all(record.batch_export_id == batch_export_id for record in records)
    assert all(record.workflow_run_id == run_id for record in records)
    assert all(record.attempt == attempt for record in records)
