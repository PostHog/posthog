"""Delivery outcomes, on the counters an alert's history reads, and one log line per send.

`app_source` is `alert`. A HogFunction delivery writes `hog_function`, so a surface showing an
alert's delivery history has to read both. An alert that moves onto native delivery otherwise
looks like its history starts over on the day it moved.

A send names its destination by the HogFunction that subscribed the destination to the event
sent. That is the id the HogFunction path records the same send under, so one destination's
sends on both paths are found by the same ids. Not the destination group's ids: a group gains and
loses ids as event kinds are switched on and off, and its history would go with them.
"""

import datetime as dt
from typing import Final
from uuid import uuid4

import structlog

from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2, KAFKA_LOG_ENTRIES
from posthog.models.event.util import format_clickhouse_timestamp

ALERT_APP_SOURCE: Final = "alert"
# `log_source_id` is the destination HogFunction id. `instance_id` is unique per send, because `log_entries`
# is a ReplacingMergeTree and two sends with the same key and microsecond would collapse into one row.
NATIVE_SEND_LOG_SOURCE: Final = "alert_destination"
NATIVE_SEND_SUCCEEDED_MESSAGE: Final = "Sent"
_MAX_ERROR_LENGTH: Final = 500

logger = structlog.get_logger(__name__)


def record_delivery(
    *,
    team_id: int,
    configuration_id: str,
    provider: str,
    destination_id: str | None,
    succeeded: bool,
    error: str | None = None,
) -> None:
    """Counts one send, and logs it when it has a destination id.

    `error` reaches the person who owns the alert, so it must already be safe to show: a
    transport's own refusal text or an exception class name, never a raw exception message.
    """
    timestamp = dt.datetime.now(dt.UTC)
    payload = {
        "team_id": team_id,
        "app_source": ALERT_APP_SOURCE,
        "app_source_id": configuration_id,
        # A destination with no HogFunction behind it, such as an insight's subscriber email, has no id.
        "instance_id": destination_id or provider,
        "timestamp": format_clickhouse_timestamp(timestamp),
        "metric_kind": "success" if succeeded else "failure",
        "metric_name": "succeeded" if succeeded else "failed",
        "count": 1,
    }
    try:
        producer = get_producer(topic=KAFKA_APP_METRICS2)
        producer.produce(topic=KAFKA_APP_METRICS2, data=payload)
        if destination_id is not None:
            producer = get_producer(topic=KAFKA_LOG_ENTRIES)
            producer.produce(
                topic=KAFKA_LOG_ENTRIES,
                data={
                    "team_id": team_id,
                    "log_source": NATIVE_SEND_LOG_SOURCE,
                    "log_source_id": destination_id,
                    "instance_id": str(uuid4()),
                    "timestamp": format_clickhouse_timestamp(timestamp),
                    "level": "INFO" if succeeded else "ERROR",
                    "message": NATIVE_SEND_SUCCEEDED_MESSAGE if succeeded else (error or "Failed")[:_MAX_ERROR_LENGTH],
                },
            )
    except Exception:
        # A counter is not worth failing a send that already reached the provider.
        logger.exception("Failed to emit alert delivery metrics", team_id=team_id, alert_id=configuration_id)
