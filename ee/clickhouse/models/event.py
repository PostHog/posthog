import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

import pytz
from dateutil.parser import isoparse
from django.utils.timezone import now
from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.element import create_elements
from ee.clickhouse.sql.events import GET_EVENTS_BY_TEAM_SQL, GET_EVENTS_SQL, INSERT_EVENT_SQL
from ee.kafka.client import ClickhouseProducer
from ee.kafka.topics import KAFKA_EVENTS
from posthog.models.element import Element
from posthog.models.team import Team


def create_event(
    event_uuid: uuid.UUID,
    event: str,
    team: Team,
    distinct_id: str,
    timestamp: Optional[Union[datetime, str]] = None,
    properties: Optional[Dict] = {},
    elements_hash: Optional[str] = "",
    elements: Optional[List[Element]] = None,
) -> str:

    if not timestamp:
        timestamp = now()

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(pytz.utc)

    if elements and not elements_hash:
        elements_hash = create_elements(event_uuid=event_uuid, elements=elements, team=team)

    data = {
        "uuid": str(event_uuid),
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
    return str(event_uuid)


def get_events():
    events = sync_execute(GET_EVENTS_SQL)
    return ClickhouseEventSerializer(events, many=True, context={"elements": None, "people": None}).data


def get_events_by_team(team_id: Union[str, int]):
    events = sync_execute(GET_EVENTS_BY_TEAM_SQL, {"team_id": str(team_id)})
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
        if len(event) >= 10 and event[8] and event[9]:
            return dict(zip(event[8], event[9]))
        else:
            return json.loads(event[2])

    def get_event(self, event):
        return event[1]

    def get_timestamp(self, event):
        dt = event[3].replace(tzinfo=timezone.utc)
        return dt.astimezone().isoformat()

    def get_person(self, event):
        if not self.context.get("people") or event[5] not in self.context["people"]:
            return event[5]
        return self.context["people"][event[5]]["properties"].get("email", event[5])

    def get_elements(self, event):
        if not event[6] or not self.context.get("elements") or event[6] not in self.context["elements"]:
            return []
        return self.context["elements"][event[6]]

    def get_elements_hash(self, event):
        return event[6]


def determine_event_conditions(conditions: Dict[str, Union[str, List[str]]]) -> Tuple[str, Dict]:
    result = ""
    params = {}
    for idx, (k, v) in enumerate(conditions.items()):
        if not isinstance(v, str):
            continue
        if k == "after":
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp > %(after)s"
            params.update({"after": timestamp})
        elif k == "before":
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp < %(before)s"
            params.update({"before": timestamp})
        elif k == "person_id":
            result += """AND distinct_id IN (
                SELECT distinct_id FROM person_distinct_id WHERE person_id = %(person_id)s AND team_id = %(team_id)s
            )"""
            params.update({"person_id": v})
        elif k == "distinct_id":
            result += "AND distinct_id = %(distinct_id)s"
            params.update({"distinct_id": v})
        elif k == "event":
            result += "AND event = %(event)s"
            params.update({"event": v})
    return result, params
