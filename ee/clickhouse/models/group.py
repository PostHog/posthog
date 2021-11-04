import datetime
import json
from typing import Dict, Optional

from django.utils.timezone import now

from ee.clickhouse.sql.groups import INSERT_GROUP_SQL
from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_GROUPS


def create_group(
    team_id: int,
    group_type_index: int,
    group_key: str,
    properties: Optional[Dict] = {},
    timestamp: Optional[datetime.datetime] = None,
):
    if not timestamp:
        timestamp = now()

    data = {
        "group_type_index": group_type_index,
        "group_key": group_key,
        "team_id": team_id,
        "group_properties": json.dumps(properties),
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_GROUPS, sql=INSERT_GROUP_SQL, data=data)
