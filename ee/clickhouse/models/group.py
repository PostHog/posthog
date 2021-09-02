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
    p.produce(
        topic=KAFKA_GROUPS,
        sql="""
        INSERT INTO groups (id, type_id, created_at, team_id, properties)
        VALUES (%(id)s, %(type_id)s, %(created_at)s, %(team_id)s, %(properties)s)
    """,
        data=data,
    )
    return id
