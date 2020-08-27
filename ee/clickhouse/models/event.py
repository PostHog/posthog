import json
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, Union

from rest_framework import serializers

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.events import GET_EVENTS_SQL, INSERT_EVENT_SQL
from posthog.models.team import Team


def create_event(
    event: str,
    team: Team,
    distinct_id: str,
    properties: Optional[Dict] = {},
    timestamp: Optional[Union[datetime, str]] = datetime.now(),
    element_hash: Optional[str] = "",
) -> None:
    ch_client.execute(
        INSERT_EVENT_SQL,
        {
            "event": event,
            "properties": json.dumps(properties),
            "timestamp": timestamp,
            "team_id": team.pk,
            "distinct_id": distinct_id,
            "element_hash": element_hash,
        },
    )


def get_events():
    events = ch_client.execute(GET_EVENTS_SQL)
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
