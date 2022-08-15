import datetime
import json
from typing import Dict, Optional, Union

import pytz
from dateutil.parser import isoparse
from django.utils.timezone import now

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_GROUPS
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.group import Group
from posthog.models.group.sql import INSERT_GROUP_SQL


def raw_create_group_ch(
    team_id: int, group_type_index: GroupTypeIndex, group_key: str, properties: Dict, timestamp: datetime.datetime
):
    """Create ClickHouse-only Group record.

    DON'T USE DIRECTLY - `create_group` is the correct option,
    unless you specifically want to sync Postgres state from ClickHouse yourself."""
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


def create_group(
    team_id: int,
    group_type_index: GroupTypeIndex,
    group_key: str,
    properties: Optional[Dict] = None,
    timestamp: Optional[Union[datetime.datetime, str]] = None,
):
    """Create proper Group record (ClickHouse + Postgres)."""
    if not properties:
        properties = {}
    if not timestamp:
        timestamp = now()

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(pytz.utc)

    raw_create_group_ch(team_id, group_type_index, group_key, properties, timestamp)
    Group.objects.create(
        team_id=team_id,
        group_type_index=group_type_index,
        group_key=group_key,
        group_properties=properties,
        created_at=timestamp,
        version=0,
    )


def get_aggregation_target_field(
    aggregation_group_type_index: Optional[GroupTypeIndex], event_table_alias: str, default: str
) -> str:
    if aggregation_group_type_index is not None:
        return f'{event_table_alias}."$group_{aggregation_group_type_index}"'
    else:
        return default
