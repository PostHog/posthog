import json
import uuid
from typing import Any, Dict, List, Optional, Union

import pytz
from dateutil.parser import isoparse
from django.utils import timezone
from rest_framework import serializers

from posthog.client import query_with_columns, sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models import Group
from posthog.models.element.element import Element, chain_to_elements, elements_to_string
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL, GET_EVENTS_BY_TEAM_SQL, INSERT_EVENT_SQL
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.settings import TEST


def create_event(
    event_uuid: uuid.UUID,
    event: str,
    team: Team,
    distinct_id: str,
    timestamp: Optional[Union[timezone.datetime, str]] = None,
    properties: Optional[Dict] = {},
    elements: Optional[List[Element]] = None,
) -> str:
    if not timestamp:
        timestamp = timezone.now()
    assert timestamp is not None

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(pytz.utc)

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
        # TODO: Support persons on events
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_EVENTS_JSON, sql=INSERT_EVENT_SQL(), data=data)

    return str(event_uuid)


def bulk_create_events(events: List[Dict[str, Any]], person_mapping: Optional[Dict[str, Person]] = None) -> None:
    """
    TEST ONLY
    Insert events in bulk. List of dicts:
    bulk_create_events([{
        "event": "user signed up",
        "distinct_id": "1",
        "team": team,
        "timestamp": "2022-01-01T12:00:00"
    }])
    """
    if not TEST:
        raise Exception("This function is only meant for setting up tests")
    inserts = []
    params: Dict[str, Any] = {}
    for index, event in enumerate(events):
        timestamp = event.get("timestamp")
        datetime64_default_timestamp = timezone.now().astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")
        if not timestamp:
            timestamp = timezone.now()
        # clickhouse specific formatting
        if isinstance(timestamp, str):
            timestamp = isoparse(timestamp)
        else:
            timestamp = timestamp.astimezone(pytz.utc)

        timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")

        elements_chain = ""
        if event.get("elements") and len(event["elements"]) > 0:
            elements_chain = elements_to_string(elements=event.get("elements"))  # type: ignore

        inserts.append(
            """(
                %(uuid_{i})s,
                %(event_{i})s,
                %(properties_{i})s,
                %(timestamp_{i})s,
                %(team_id_{i})s,
                %(distinct_id_{i})s,
                %(elements_chain_{i})s,
                %(person_id_{i})s,
                %(person_properties_{i})s,
                %(person_created_at_{i})s,
                %(group0_properties_{i})s,
                %(group1_properties_{i})s,
                %(group2_properties_{i})s,
                %(group3_properties_{i})s,
                %(group4_properties_{i})s,
                %(group0_created_at_{i})s,
                %(group1_created_at_{i})s,
                %(group2_created_at_{i})s,
                %(group3_created_at_{i})s,
                %(group4_created_at_{i})s,
                %(created_at_{i})s,
                now(),
                0
            )""".format(
                i=index
            )
        )

        #  use person properties mapping to populate person properties in given event
        team_id = event["team"].pk if event.get("team") else event["team_id"]
        if person_mapping and person_mapping.get(event["distinct_id"]):
            person = person_mapping[event["distinct_id"]]
            person_properties = person.properties
            person_id = person.uuid
            person_created_at = person.created_at
        else:
            try:
                person = Person.objects.get(
                    persondistinctid__distinct_id=event["distinct_id"], persondistinctid__team_id=team_id
                )
                person_properties = person.properties
                person_id = person.uuid
                person_created_at = person.created_at
            except Person.DoesNotExist:
                person_properties = {}
                person_id = uuid.uuid4()
                person_created_at = datetime64_default_timestamp

        event = {
            **event,
            "person_properties": {**person_properties, **event.get("person_properties", {})},
            "person_id": person_id,
            "person_created_at": person_created_at,
        }

        # Populate group properties as well
        for property_key, value in (event.get("properties") or {}).items():
            if property_key.startswith("$group_"):
                group_type_index = property_key[-1]
                try:
                    group = Group.objects.get(team_id=team_id, group_type_index=group_type_index, group_key=value)
                    group_property_key = f"group{group_type_index}_properties"
                    group_created_at_key = f"group{group_type_index}_created_at"

                    event = {
                        **event,
                        group_property_key: {**group.group_properties, **event.get(group_property_key, {})},
                        group_created_at_key: event.get(group_created_at_key, datetime64_default_timestamp),
                    }

                except Group.DoesNotExist:
                    continue

        event = {
            "uuid": str(event["event_uuid"]) if event.get("event_uuid") else str(uuid.uuid4()),
            "event": event["event"],
            "properties": json.dumps(event["properties"]) if event.get("properties") else "{}",
            "timestamp": timestamp,
            "team_id": team_id,
            "distinct_id": str(event["distinct_id"]),
            "elements_chain": elements_chain,
            "created_at": timestamp,
            "person_id": event["person_id"] if event.get("person_id") else str(uuid.uuid4()),
            "person_properties": json.dumps(event["person_properties"]) if event.get("person_properties") else "{}",
            "person_created_at": event["person_created_at"]
            if event.get("person_created_at")
            else datetime64_default_timestamp,
            "group0_properties": json.dumps(event["group0_properties"]) if event.get("group0_properties") else "{}",
            "group1_properties": json.dumps(event["group1_properties"]) if event.get("group1_properties") else "{}",
            "group2_properties": json.dumps(event["group2_properties"]) if event.get("group2_properties") else "{}",
            "group3_properties": json.dumps(event["group3_properties"]) if event.get("group3_properties") else "{}",
            "group4_properties": json.dumps(event["group4_properties"]) if event.get("group4_properties") else "{}",
            "group0_created_at": event["group0_created_at"]
            if event.get("group0_created_at")
            else datetime64_default_timestamp,
            "group1_created_at": event["group1_created_at"]
            if event.get("group1_created_at")
            else datetime64_default_timestamp,
            "group2_created_at": event["group2_created_at"]
            if event.get("group2_created_at")
            else datetime64_default_timestamp,
            "group3_created_at": event["group3_created_at"]
            if event.get("group3_created_at")
            else datetime64_default_timestamp,
            "group4_created_at": event["group4_created_at"]
            if event.get("group4_created_at")
            else datetime64_default_timestamp,
        }

        params = {**params, **{"{}_{}".format(key, index): value for key, value in event.items()}}
    sync_execute(BULK_INSERT_EVENT_SQL() + ", ".join(inserts), params, flush=False)


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
