import datetime
import json
from typing import Dict, Optional

from django.utils.timezone import now

from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_GROUPS
from posthog.models.utils import UUIDT


def create_group(
    team_id: int,
    type_id: int,
    id: Optional[str] = None,
    properties: Optional[Dict] = {},
    timestamp: Optional[datetime.datetime] = None,
) -> str:
    if id is None:
        id = str(UUIDT())

    if not timestamp:
        timestamp = now()

    data = {
        "id": str(id),
        "type_id": type_id,
        "team_id": team_id,
        "properties": json.dumps(properties),
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
    }
    p = ClickhouseProducer()
    # :TODO: Groups insert statement
    p.produce(topic=KAFKA_GROUPS, sql="", data=data)
    return id
