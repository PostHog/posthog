import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

import pytz
from dateutil.parser import isoparse
from rest_framework import serializers

from ee.clickhouse.client import async_execute, sync_execute
from ee.clickhouse.models.clickhouse import generate_clickhouse_uuid
from ee.clickhouse.models.element import create_elements
from ee.clickhouse.sql.events import GET_EVENTS_SQL, INSERT_EVENT_SQL
from ee.kafka.client import ClickhouseProducer
from ee.kafka.topics import KAFKA_EVENTS
from posthog.models.element import Element
from posthog.models.team import Team


def create_event(
    event: str,
    team: Team,
    distinct_id: str,
    timestamp: Optional[Union[datetime, str]],
    properties: Optional[Dict] = {},
    elements_hash: Optional[str] = "",
    elements: Optional[List[Element]] = None,
) -> None:

    if not timestamp:
        timestamp = datetime.now()

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(pytz.utc)

    if elements and not elements_hash:
        elements_hash = create_elements(elements=elements, team=team)

    event_id = generate_clickhouse_uuid()

    data = {
        "id": str(event_id),
        "event": event,
        "properties": json.dumps(properties),
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "team_id": team.pk,
        "distinct_id": distinct_id,
        "elements_hash": elements_hash,
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
    }
    p = ClickhouseProducer()
    p.produce(sql=INSERT_EVENT_SQL, topic=KAFKA_EVENTS, data=data)


def get_events():
    events = sync_execute(GET_EVENTS_SQL)
    return ClickhouseEventSerializer(events, many=True, context={"elements": None, "people": None}).data


# reference raw sql for
class ClickhouseEventSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    properties = serializers.SerializerMethodField()
    event = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()
    person = serializers.SerializerMethodField()
    elements = serializers.SerializerMethodField()
    elements_hash = serializers.SerializerMethodField()

    def get_id(self, event):
        return str(event[0])

    def get_properties(self, event):
        return dict(zip(event[8], event[9]))

    def get_event(self, event):
        return event[1]

    def get_timestamp(self, event):
        dt = event[3].replace(tzinfo=timezone.utc)
        return dt.astimezone().isoformat()

    def get_person(self, event):
        return event[5]

    def get_elements(self, event):
        return []

    def get_elements_hash(self, event):
        return event[6]


def determine_event_conditions(conditions: Dict[str, str]) -> Tuple[str, Dict]:
    result = ""
    params = {}
    for idx, (k, v) in enumerate(conditions.items()):
        if k == "after":
            result += "AND timestamp > %(after)s"
            params.update({"after": v})
        elif k == "before":
            result += "AND timestamp < %(before)s"
            params.update({"before": v})
    return result, params
