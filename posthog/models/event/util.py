import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Optional, Union
from zoneinfo import ZoneInfo

from django.utils import timezone

from dateutil.parser import isoparse
from rest_framework import serializers

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models import Group
from posthog.models.element.element import Element, chain_to_elements, elements_to_string
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL, INSERT_EVENT_SQL
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.settings import TEST

ZERO_DATE = datetime(1970, 1, 1)


def create_event(
    event_uuid: uuid.UUID,
    event: str,
    team: Team,
    distinct_id: str,
    timestamp: Optional[Union[datetime, str]] = None,
    properties: Optional[dict] = None,
    elements: Optional[list[Element]] = None,
    person_id: Optional[uuid.UUID] = None,
    person_properties: Optional[dict] = None,
    person_created_at: Optional[Union[datetime, str]] = None,
    group0_properties: Optional[dict] = None,
    group1_properties: Optional[dict] = None,
    group2_properties: Optional[dict] = None,
    group3_properties: Optional[dict] = None,
    group4_properties: Optional[dict] = None,
    group0_created_at: Optional[Union[datetime, str]] = None,
    group1_created_at: Optional[Union[datetime, str]] = None,
    group2_created_at: Optional[Union[datetime, str]] = None,
    group3_created_at: Optional[Union[datetime, str]] = None,
    group4_created_at: Optional[Union[datetime, str]] = None,
    person_mode: Literal["full", "propertyless", "force_upgrade"] = "full",
) -> str:
    if properties is None:
        properties = {}
    if not timestamp:
        timestamp = timezone.now()
    assert timestamp is not None

    timestamp = isoparse(timestamp) if isinstance(timestamp, str) else timestamp.astimezone(ZoneInfo("UTC"))

    elements_chain = ""
    if elements and len(elements) > 0:
        elements_chain = elements_to_string(elements=elements)

    data = {
        "uuid": str(event_uuid),
        "event": event,
        "properties": json.dumps(properties),
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "team_id": team.id,
        "project_id": team.project_id,
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
        "person_mode": person_mode,
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_EVENTS_JSON, sql=INSERT_EVENT_SQL(), data=data)

    return str(event_uuid)


def format_clickhouse_timestamp(
    raw_timestamp: Optional[Union[datetime, str]],
    default=None,
) -> str:
    if default is None:
        default = timezone.now()
    parsed_datetime = (
        isoparse(raw_timestamp)
        if isinstance(raw_timestamp, str)
        else (raw_timestamp or default).astimezone(ZoneInfo("UTC"))
    )
    return parsed_datetime.strftime("%Y-%m-%d %H:%M:%S.%f")


def bulk_create_events(
    events: list[dict[str, Any]],
    person_mapping: Optional[dict[str, Person]] = None,
) -> None:
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
    params: dict[str, Any] = {}
    for index, event in enumerate(events):
        datetime64_default_timestamp = timezone.now().astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        _timestamp = event.get("_timestamp") or datetime.now()
        timestamp = event.get("timestamp") or datetime.now()
        if isinstance(timestamp, str):
            timestamp = isoparse(timestamp)
        # Offset timezone-naive datetime by project timezone, to facilitate @also_test_with_different_timezones
        if timestamp.tzinfo is None:
            team_timezone = event["team"].timezone if event.get("team") else "UTC"
            timestamp = timestamp.replace(tzinfo=ZoneInfo(team_timezone))
        # Format for ClickHouse
        timestamp = timestamp.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S.%f")

        elements_chain = ""
        if tentative_elements_chain := event.get("elements_chain"):
            assert isinstance(tentative_elements_chain, str)
            elements_chain = tentative_elements_chain
        elif tentative_elements := event.get("elements"):
            assert isinstance(tentative_elements, list)
            elements_chain = elements_to_string(elements=tentative_elements)

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
                %(person_mode_{i})s,
                %(created_at_{i})s,
                %(_timestamp_{i})s,
                0
            )""".format(i=index)
        )

        #  use person properties mapping to populate person properties in given event
        team_id = event.get("team_id") or event["team"].pk
        person_mode = event.get("person_mode", "full")
        if person_mapping and person_mapping.get(event["distinct_id"]):
            person = person_mapping[event["distinct_id"]]
            person_properties = person.properties
            person_id = person.uuid
            person_created_at = person.created_at
        else:
            try:
                person = Person.objects.get(
                    persondistinctid__distinct_id=event["distinct_id"],
                    persondistinctid__team_id=team_id,
                )
                person_properties = person.properties
                person_id = person.uuid
                person_created_at = person.created_at
            except Person.DoesNotExist:
                person_properties = {}
                person_id = event.get("person_id", uuid.uuid4())
                person_created_at = datetime64_default_timestamp

        event = {
            **event,
            "person_properties": {
                **person_properties,
                **event.get("person_properties", {}),
            },
            "person_id": person_id,
            "person_created_at": person_created_at,
        }

        # Populate group properties as well
        for property_key, value in (event.get("properties") or {}).items():
            if property_key.startswith("$group_"):
                group_type_index = property_key[-1]
                try:
                    group = Group.objects.get(
                        team_id=team_id,
                        group_type_index=group_type_index,
                        group_key=value,
                    )
                    group_property_key = f"group{group_type_index}_properties"
                    group_created_at_key = f"group{group_type_index}_created_at"

                    event = {
                        **event,
                        group_property_key: {
                            **group.group_properties,
                            **event.get(group_property_key, {}),
                        },
                        group_created_at_key: event.get(group_created_at_key, datetime64_default_timestamp),
                    }

                except Group.DoesNotExist:
                    continue
        properties = event.get("properties", {})

        event = {
            "uuid": str(event["event_uuid"]) if event.get("event_uuid") else str(uuid.uuid4()),
            "event": event["event"],
            "properties": json.dumps(properties),
            "timestamp": timestamp,
            "team_id": team_id,
            "distinct_id": str(event["distinct_id"]),
            "elements_chain": elements_chain,
            "created_at": timestamp,
            "person_id": event["person_id"] if event.get("person_id") else str(uuid.uuid4()),
            "person_properties": json.dumps(event["person_properties"]) if event.get("person_properties") else "{}",
            "person_created_at": (
                event["person_created_at"] if event.get("person_created_at") else datetime64_default_timestamp
            ),
            "group0_properties": json.dumps(event["group0_properties"]) if event.get("group0_properties") else "{}",
            "group1_properties": json.dumps(event["group1_properties"]) if event.get("group1_properties") else "{}",
            "group2_properties": json.dumps(event["group2_properties"]) if event.get("group2_properties") else "{}",
            "group3_properties": json.dumps(event["group3_properties"]) if event.get("group3_properties") else "{}",
            "group4_properties": json.dumps(event["group4_properties"]) if event.get("group4_properties") else "{}",
            "group0_created_at": (
                event["group0_created_at"] if event.get("group0_created_at") else datetime64_default_timestamp
            ),
            "group1_created_at": (
                event["group1_created_at"] if event.get("group1_created_at") else datetime64_default_timestamp
            ),
            "group2_created_at": (
                event["group2_created_at"] if event.get("group2_created_at") else datetime64_default_timestamp
            ),
            "group3_created_at": (
                event["group3_created_at"] if event.get("group3_created_at") else datetime64_default_timestamp
            ),
            "group4_created_at": (
                event["group4_created_at"] if event.get("group4_created_at") else datetime64_default_timestamp
            ),
            "_timestamp": _timestamp,
            "person_mode": person_mode,
        }

        params = {
            **params,
            **{"{}_{}".format(key, index): value for key, value in event.items()},
        }
    sync_execute(BULK_INSERT_EVENT_SQL() + ", ".join(inserts), params, flush=False)


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


def parse_properties(properties: str, allow_list: Optional[set[str]] = None) -> dict:
    # parse_constants gets called for any NaN, Infinity etc values
    # we just want those to be returned as None
    if allow_list is None:
        allow_list = set()
    props = json.loads(properties or "{}", parse_constant=lambda x: None)
    return {
        key: value.strip('"') if isinstance(value, str) else value
        for key, value in props.items()
        if not allow_list or key in allow_list
    }


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
        return parse_properties(event["properties"])

    def get_event(self, event):
        return event["event"]

    def get_timestamp(self, event):
        dt = event["timestamp"].replace(tzinfo=UTC)
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


def get_agg_event_count_for_teams(team_ids: list[Union[str, int]]) -> int:
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM events
        WHERE team_id IN (%(team_id_clause)s)
    """,
        {"team_id_clause": team_ids},
    )[0][0]
    return result


def get_agg_events_with_groups_count_for_teams_and_period(
    team_ids: list[Union[str, int]], begin: datetime, end: datetime
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
    """
    ```SELECT count(1) as count FROM events``` is too slow on cloud
    """
    result = sync_execute(
        """
        SELECT sum(rows) FROM system.parts WHERE (active = 1) AND (table = 'sharded_events')
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
