import json
import uuid
from typing import Dict, List, Optional, Union

import pytz
from dateutil.parser import isoparse
from django.utils import timezone
from rest_framework import serializers

from posthog.client import query_with_columns, sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models.element.element import Element, chain_to_elements, elements_to_string
from posthog.models.event.sql import GET_EVENTS_BY_TEAM_SQL, INSERT_EVENT_SQL
from posthog.models.team import Team
from posthog.queries.actor_base_query import EventInfoForRecording

ZERO_DATE = timezone.datetime(1970, 1, 1)


def create_event(
    event_uuid: uuid.UUID,
    event: str,
    team: Team,
    distinct_id: str,
    timestamp: Optional[Union[timezone.datetime, str]] = None,
    properties: Optional[Dict] = {},
    elements: Optional[List[Element]] = None,
    person_id: Optional[uuid.UUID] = None,
    person_properties: Optional[Dict] = None,
    person_created_at: Optional[Union[timezone.datetime, str]] = None,
    group0_properties: Optional[Dict] = None,
    group1_properties: Optional[Dict] = None,
    group2_properties: Optional[Dict] = None,
    group3_properties: Optional[Dict] = None,
    group4_properties: Optional[Dict] = None,
    group0_created_at: Optional[Union[timezone.datetime, str]] = None,
    group1_created_at: Optional[Union[timezone.datetime, str]] = None,
    group2_created_at: Optional[Union[timezone.datetime, str]] = None,
    group3_created_at: Optional[Union[timezone.datetime, str]] = None,
    group4_created_at: Optional[Union[timezone.datetime, str]] = None,
) -> str:
    if not timestamp:
        timestamp = timezone.now()
    assert timestamp is not None

    timestamp = isoparse(timestamp) if isinstance(timestamp, str) else timestamp.astimezone(pytz.utc)

    elements_chain = ""
    if elements and len(elements) > 0:
        elements_chain = elements_to_string(elements=elements)

    data = {
        "uuid": str(event_uuid),
        "event": event,
        "properties": json.dumps(properties),
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "team_id": team.pk,
        "distinct_id": str(distinct_id),
        "elements_chain": elements_chain,
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "person_id": str(person_id) if person_id else "00000000-0000-0000-0000-000000000000",
        "person_properties": json.dumps(person_properties) if person_properties is not None else "",
        "person_created_at": format_clickhouse_timestamp(person_created_at, ZERO_DATE),
        "group0_properties": json.dumps(group0_properties) if group0_properties is not None else "",
        "group1_properties": json.dumps(group1_properties) if group1_properties is not None else "",
        "group2_properties": json.dumps(group2_properties) if group2_properties is not None else "",
        "group3_properties": json.dumps(group3_properties) if group3_properties is not None else "",
        "group4_properties": json.dumps(group4_properties) if group4_properties is not None else "",
        "group0_created_at": format_clickhouse_timestamp(group0_created_at, ZERO_DATE),
        "group1_created_at": format_clickhouse_timestamp(group1_created_at, ZERO_DATE),
        "group2_created_at": format_clickhouse_timestamp(group2_created_at, ZERO_DATE),
        "group3_created_at": format_clickhouse_timestamp(group3_created_at, ZERO_DATE),
        "group4_created_at": format_clickhouse_timestamp(group4_created_at, ZERO_DATE),
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_EVENTS_JSON, sql=INSERT_EVENT_SQL(), data=data)

    return str(event_uuid)


def format_clickhouse_timestamp(
    raw_timestamp: Optional[Union[timezone.datetime, str]],
    default=timezone.now(),
) -> str:
    parsed_datetime = (
        isoparse(raw_timestamp) if isinstance(raw_timestamp, str) else (raw_timestamp or default).astimezone(pytz.utc)
    )
    return parsed_datetime.strftime("%Y-%m-%d %H:%M:%S.%f")


def get_events_by_team(team_id: Union[str, int]):

    events = query_with_columns(GET_EVENTS_BY_TEAM_SQL, {"team_id": str(team_id)})
    return ClickhouseEventSerializer(events, many=True, context={"elements": None, "people": None}).data


class ElementSerializer(serializers.ModelSerializer):
    event = serializers.CharField()

    class Meta:
        model = Element
        fields = [
            "event",
            "text",
            "tag_name",
            "attr_class",
            "href",
            "attr_id",
            "nth_child",
            "nth_of_type",
            "attributes",
            "order",
        ]


# reference raw sql for
class ClickhouseEventSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    distinct_id = serializers.SerializerMethodField()
    properties = serializers.SerializerMethodField()
    event = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()
    person = serializers.SerializerMethodField()
    elements = serializers.SerializerMethodField()
    elements_chain = serializers.SerializerMethodField()
    matched_recordings = serializers.SerializerMethodField()

    def get_id(self, event):
        return str(event["uuid"])

    def get_distinct_id(self, event):
        return event["distinct_id"]

    def get_properties(self, event):
        # parse_constants gets called for any NaN, Infinity etc values
        # we just want those to be returned as None
        props = json.loads(event["properties"], parse_constant=lambda x: None)
        unpadded = {key: value.strip('"') if isinstance(value, str) else value for key, value in props.items()}
        return unpadded

    def get_event(self, event):
        return event["event"]

    def get_timestamp(self, event):
        dt = event["timestamp"].replace(tzinfo=timezone.utc)
        return dt.astimezone().isoformat()

    def get_person(self, event):
        if not self.context.get("people") or event["distinct_id"] not in self.context["people"]:
            return None

        person = self.context["people"][event["distinct_id"]]
        return {
            "is_identified": person.is_identified,
            "distinct_ids": person.distinct_ids[:1],  # only send the first one to avoid a payload bloat
            "properties": {
                key: person.properties[key] for key in ["email", "name", "username"] if key in person.properties
            },
        }

    def get_elements(self, event):
        if not event["elements_chain"]:
            return []
        return ElementSerializer(chain_to_elements(event["elements_chain"]), many=True).data

    def get_elements_chain(self, event):
        return event["elements_chain"]

    def get_matched_recordings(self, event):
        return (
            [
                {
                    "session_id": event["session_id"],
                    "events": [
                        EventInfoForRecording(
                            timestamp=event["timestamp"], uuid=event["uuid"], window_id=event["window_id"]
                        )
                    ],
                }
            ]
            if event.get("session_id", None)
            else []
        )


def get_event_count_for_team_and_period(
    team_id: Union[str, int], begin: timezone.datetime, end: timezone.datetime
) -> int:
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM events
        WHERE team_id = %(team_id)s
        AND timestamp between %(begin)s AND %(end)s
    """,
        {"team_id": str(team_id), "begin": begin, "end": end},
    )[0][0]
    return result


def get_agg_event_count_for_teams(team_ids: List[Union[str, int]]) -> int:
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM events
        WHERE team_id IN (%(team_id_clause)s)
    """,
        {"team_id_clause": team_ids},
    )[0][0]
    return result


def get_agg_event_count_for_teams_and_period(
    team_ids: List[Union[str, int]], begin: timezone.datetime, end: timezone.datetime
) -> int:
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM events
        WHERE team_id IN (%(team_id_clause)s)
        AND timestamp between %(begin)s AND %(end)s
    """,
        {"team_id_clause": team_ids, "begin": begin, "end": end},
    )[0][0]
    return result


def get_agg_events_with_groups_count_for_teams_and_period(
    team_ids: List[Union[str, int]], begin: timezone.datetime, end: timezone.datetime
) -> int:
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM events
        WHERE team_id IN (%(team_id_clause)s)
        AND timestamp between %(begin)s AND %(end)s
        AND ($group_0 != '' OR $group_1 != '' OR $group_2 != '' OR $group_3 != '' OR $group_4 != '')
    """,
        {"team_id_clause": team_ids, "begin": begin, "end": end},
    )[0][0]
    return result


def get_event_count_for_team(team_id: Union[str, int]) -> int:
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM events
        WHERE team_id = %(team_id)s
    """,
        {"team_id": str(team_id)},
    )[0][0]
    return result


def get_event_count() -> int:
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM events
    """
    )[0][0]
    return result


def get_event_count_for_last_month() -> int:
    result = sync_execute(
        """
        -- count of events last month
        SELECT
        COUNT(1) freq
        FROM events
        WHERE
        toStartOfMonth(timestamp) = toStartOfMonth(date_sub(MONTH, 1, now()))
    """
    )[0][0]
    return result


def get_event_count_month_to_date() -> int:
    result = sync_execute(
        """
        -- count of events month to date
        SELECT
        COUNT(1) freq
        FROM events
        WHERE toStartOfMonth(timestamp) = toStartOfMonth(now());
    """
    )[0][0]
    return result


def get_events_count_for_team_by_client_lib(
    team_id: Union[str, int], begin: timezone.datetime, end: timezone.datetime
) -> dict:
    results = sync_execute(
        """
        SELECT JSONExtractString(properties, '$lib') as lib, COUNT(1) as freq
        FROM events
        WHERE team_id = %(team_id)s
        AND timestamp between %(begin)s AND %(end)s
        GROUP BY lib
    """,
        {"team_id": str(team_id), "begin": begin, "end": end},
    )
    return {result[0]: result[1] for result in results}


def get_events_count_for_team_by_event_type(
    team_id: Union[str, int], begin: timezone.datetime, end: timezone.datetime
) -> dict:
    results = sync_execute(
        """
        SELECT event, COUNT(1) as freq
        FROM events
        WHERE team_id = %(team_id)s
        AND timestamp between %(begin)s AND %(end)s
        GROUP BY event
    """,
        {"team_id": str(team_id), "begin": begin, "end": end},
    )
    return {result[0]: result[1] for result in results}
