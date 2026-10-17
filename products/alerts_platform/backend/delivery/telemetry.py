"""Delivery outcomes, on the counters an alert's history reads.

`app_source` is `alert`. A HogFunction delivery writes `hog_function`, so a surface showing an
alert's delivery history has to read both. An alert that moves onto native delivery otherwise
looks like its history starts over on the day it moved.
"""

import datetime as dt
from typing import Final

import structlog

from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp

ALERT_APP_SOURCE: Final = "alert"

logger = structlog.get_logger(__name__)


def record_delivery(*, team_id: int, configuration_id: str, provider: str, succeeded: bool) -> None:
    payload = {
        "team_id": team_id,
        "app_source": ALERT_APP_SOURCE,
        "app_source_id": configuration_id,
        "instance_id": provider,
        "timestamp": format_clickhouse_timestamp(dt.datetime.now(dt.UTC)),
        "metric_kind": "success" if succeeded else "failure",
        "metric_name": "succeeded" if succeeded else "failed",
        "count": 1,
    }
    try:
        producer = get_producer(topic=KAFKA_APP_METRICS2)
        producer.produce(topic=KAFKA_APP_METRICS2, data=payload)
    except Exception:
        # A counter is not worth failing a send that already reached the provider.
        logger.exception("Failed to emit alert delivery metrics", team_id=team_id, alert_id=configuration_id)
