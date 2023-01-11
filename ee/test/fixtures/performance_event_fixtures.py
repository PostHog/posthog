import uuid
from datetime import datetime
from typing import Optional

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_PERFORMANCE_EVENTS
from posthog.models.performance.sql import PERFORMANCE_EVENT_DATA_TABLE
from posthog.utils import cast_timestamp_or_now


def create_performance_event(
    team_id: int,
    distinct_id: str,
    session_id: str,
    window_id: str = "window_1",
    current_url: str = "https://posthog.com",
    timestamp: Optional[datetime] = None,
    entry_type="resource",
    **kwargs,
) -> str:
    timestamp_str = cast_timestamp_or_now(timestamp)

    data = {
        "uuid": str(uuid.uuid4()),
        "team_id": team_id,
        "distinct_id": distinct_id,
        "session_id": session_id,
        "window_id": window_id,
        "pageview_id": window_id,
        "current_url": current_url,
        "timestamp": timestamp_str,
        "entry_type": entry_type,
        "name": "https://posthog.com/static/js/1.0.0/PostHog.js",
    }

    data.update(kwargs)

    selects = [f"%({x})s" for x in data.keys()]
    sql = f"""
INSERT INTO {PERFORMANCE_EVENT_DATA_TABLE()} ({', '.join(data.keys()) }, _timestamp, _offset)
SELECT {', '.join(selects) }, now(), 0
"""

    p = ClickhouseProducer()
    p.produce(sql=sql, topic=KAFKA_PERFORMANCE_EVENTS, data=data)

    return str(uuid)
