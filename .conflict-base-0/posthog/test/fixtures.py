from datetime import datetime
from typing import Optional

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.app_metrics2.sql import INSERT_APP_METRICS2_SQL
from posthog.models.event.util import format_clickhouse_timestamp


def create_app_metric2(
    team_id: int,
    app_source: str,
    timestamp: Optional[datetime] = None,
    app_source_id: str = "12345",
    instance_id: str = "54321",
    metric_kind: str = "success",
    metric_name: str = "succeeded",
    count: int = 1,
):
    data = {
        "timestamp": format_clickhouse_timestamp(timestamp or datetime.now()),
        "team_id": team_id,
        "app_source": app_source,
        "app_source_id": app_source_id,
        "instance_id": instance_id,
        "metric_kind": metric_kind,
        "metric_name": metric_name,
        "count": count,
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_APP_METRICS2, sql=INSERT_APP_METRICS2_SQL, data=data)
