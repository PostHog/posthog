import datetime
import json
from typing import Dict, Optional

from django.utils.timezone import now

from ee.clickhouse.sql.groups import INSERT_GROUP_SQL
from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_GROUPS
from posthog.models import Group
from posthog.models.filters.utils import GroupTypeIndex


def create_group(
    team_id: int,
    group_type_index: GroupTypeIndex,
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

    Group.objects.create(
        team_id=team_id, group_type_index=group_type_index, group_key=group_key, group_properties=properties, version=0,
    )


def get_aggregation_target_field(
    aggregation_group_type_index: Optional[GroupTypeIndex], event_table_alias: str, default: str
) -> str:
    if aggregation_group_type_index is not None:
        return f'{event_table_alias}."$group_{aggregation_group_type_index}"'
    else:
        return default
