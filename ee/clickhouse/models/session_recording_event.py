import datetime
import json
import uuid
from typing import Dict, List, Optional, Tuple, Union

from dateutil.parser import isoparse
from django.utils import timezone

from ee.clickhouse.models.util import cast_timestamp_or_now
from ee.clickhouse.sql.session_recording_events import INSERT_SESSION_RECORDING_EVENT_SQL
from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_SESSION_RECORDING_EVENTS


def create_session_recording_event(
    uuid: uuid.UUID,
    team_id: int,
    distinct_id: str,
    session_id: str,
    timestamp: Union[datetime.datetime, str],
    snapshot_data: dict,
) -> str:
    timestamp = cast_timestamp_or_now(timestamp)

    data = {
        "uuid": str(uuid),
        "team_id": team_id,
        "distinct_id": distinct_id,
        "session_id": session_id,
        "snapshot_data": json.dumps(snapshot_data),
        "timestamp": timestamp,
        "created_at": timestamp,
    }
    p = ClickhouseProducer()
    p.produce(sql=INSERT_SESSION_RECORDING_EVENT_SQL, topic=KAFKA_SESSION_RECORDING_EVENTS, data=data)
    return str(uuid)
