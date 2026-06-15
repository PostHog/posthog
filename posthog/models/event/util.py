import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Optional, Union
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from dateutil.parser import isoparse
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models.element.element import Element, chain_to_elements, elements_to_string
from posthog.models.event.sql import (
    BULK_INSERT_EVENT_SQL,
    EVENTS_DATA_TABLE,
    EVENTS_INSERT_DATA_TABLE,
    EVENTS_QUERY_TABLE,
    INSERT_EVENT_SQL,
)
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.settings import TEST

ZERO_DATE = datetime(1970, 1, 1)
CLICKHOUSE_JSON_MIN_INT = -(2**63)
CLICKHOUSE_JSON_MAX_UINT = 2**64 - 1


def _normalize_clickhouse_json_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        if CLICKHOUSE_JSON_MIN_INT <= value <= CLICKHOUSE_JSON_MAX_UINT:
            return value
        return float(value)
    if isinstance(value, list):
        return [_normalize_clickhouse_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_clickhouse_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_clickhouse_json_value(nested_value) for key, nested_value in value.items()}
    return value


def _json_dumps_for_clickhouse(value: dict[str, Any]) -> str:
    return json.dumps(_normalize_clickhouse_json_value(value))


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
        "properties": _json_dumps_for_clickhouse(properties),
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "team_id": team.id,
        "project_id": team.project_id,
        "distinct_id": str(distinct_id),
        "elements_chain": elements_chain,
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "person_id": str(person_id) if person_id else "00000000-0000-0000-0000-000000000000",
        "person_properties": _json_dumps_for_clickhouse(person_properties) if person_properties is not None else "{}",
        "person_created_at": format_clickhouse_timestamp(person_created_at, ZERO_DATE),
        "group0_properties": _json_dumps_for_clickhouse(group0_properties) if group0_properties is not None else "{}",
        "group1_properties": _json_dumps_for_clickhouse(group1_properties) if group1_properties is not None else "{}",
        "group2_properties": _json_dumps_for_clickhouse(group2_properties) if group2_properties is not None else "{}",
        "group3_properties": _json_dumps_for_clickhouse(group3_properties) if group3_properties is not None else "{}",
        "group4_properties": _json_dumps_for_clickhouse(group4_properties) if group4_properties is not None else "{}",
        "group0_created_at": format_clickhouse_timestamp(group0_created_at, ZERO_DATE),
        "group1_created_at": format_clickhouse_timestamp(group1_created_at, ZERO_DATE),
        "group2_created_at": format_clickhouse_timestamp(group2_created_at, ZERO_DATE),
        "group3_created_at": format_clickhouse_timestamp(group3_created_at, ZERO_DATE),
        "group4_created_at": format_clickhouse_timestamp(group4_created_at, ZERO_DATE),
        "person_mode": person_mode,
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_EVENTS_JSON, sql=INSERT_EVENT_SQL(), data=data)
    if TEST and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        p.produce(topic=KAFKA_EVENTS_JSON, sql=INSERT_EVENT_SQL(table_name=EVENTS_DATA_TABLE()), data=data)

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
        person_created_at: Any
        if person_mapping and person_mapping.get(event["distinct_id"]):
            person = person_mapping[event["distinct_id"]]
            person_properties = person.properties
            person_id = person.uuid
            person_created_at = person.created_at or datetime64_default_timestamp
        else:
            try:
                person = Person.objects.get(  # nosemgrep: no-direct-persons-db-orm
                    persondistinctid__distinct_id=event["distinct_id"],
                    persondistinctid__team_id=team_id,
                )
                person_properties = person.properties
                person_id = person.uuid
                person_created_at = person.created_at or datetime64_default_timestamp
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
        from posthog.models.group.util import get_group_by_key

        for property_key, value in (event.get("properties") or {}).items():
            if property_key.startswith("$group_"):
                group_type_index = property_key[-1]
                group = get_group_by_key(team_id, int(group_type_index), value)
                if group is None:
                    continue
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
        properties = event.get("properties", {})

        event = {
            "uuid": str(event["event_uuid"]) if event.get("event_uuid") else str(uuid.uuid4()),
            "event": event["event"],
            "properties": _json_dumps_for_clickhouse(properties),
            "timestamp": timestamp,
            "team_id": team_id,
            "distinct_id": str(event["distinct_id"]),
            "elements_chain": elements_chain,
            "created_at": timestamp,
            "person_id": event["person_id"] if event.get("person_id") else str(uuid.uuid4()),
            "person_properties": (
                _json_dumps_for_clickhouse(event["person_properties"]) if event.get("person_properties") else "{}"
            ),
            "person_created_at": (
                event["person_created_at"] if event.get("person_created_at") else datetime64_default_timestamp
            ),
            "group0_properties": (
                _json_dumps_for_clickhouse(event["group0_properties"]) if event.get("group0_properties") else "{}"
            ),
            "group1_properties": (
                _json_dumps_for_clickhouse(event["group1_properties"]) if event.get("group1_properties") else "{}"
            ),
            "group2_properties": (
                _json_dumps_for_clickhouse(event["group2_properties"]) if event.get("group2_properties") else "{}"
            ),
            "group3_properties": (
                _json_dumps_for_clickhouse(event["group3_properties"]) if event.get("group3_properties") else "{}"
            ),
            "group4_properties": (
                _json_dumps_for_clickhouse(event["group4_properties"]) if event.get("group4_properties") else "{}"
            ),
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
    if TEST and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        sync_execute(BULK_INSERT_EVENT_SQL(table_name=EVENTS_DATA_TABLE()) + ", ".join(inserts), params, flush=False)


@extend_schema_serializer(component_name="EventElement")
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

    @extend_schema_field(serializers.CharField())
    def get_id(self, event):
        return str(event["uuid"])

    @extend_schema_field(serializers.CharField())
    def get_distinct_id(self, event):
        return event["distinct_id"]

    @extend_schema_field(serializers.DictField())
    def get_properties(self, event):
        properties_column = "event_properties" if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA else "properties"
        props = parse_properties(event[properties_column])
        restricted = self.context.get("restricted_event_properties")
        if restricted:
            props = {k: v for k, v in props.items() if k not in restricted}

        restricted_person = self.context.get("restricted_person_properties")
        if restricted_person:
            for key in ("$set", "$set_once"):
                nested = props.get(key)
                if isinstance(nested, dict):
                    props[key] = {k: v for k, v in nested.items() if k not in restricted_person}
            unset = props.get("$unset")
            if isinstance(unset, list):
                props["$unset"] = [k for k in unset if k not in restricted_person]
        return props

    @extend_schema_field(serializers.CharField())
    def get_event(self, event):
        return event["event"]

    @extend_schema_field(serializers.DateTimeField())
    def get_timestamp(self, event):
        dt = event["timestamp"].replace(tzinfo=UTC)
        return dt.astimezone().isoformat()

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_person(self, event):
        if not self.context.get("people") or event["distinct_id"] not in self.context["people"]:
            return None

        person = self.context["people"][event["distinct_id"]]
        restricted = self.context.get("restricted_person_properties", set())
        return {
            "is_identified": person.is_identified,
            "distinct_ids": person.distinct_ids[:1],  # only send the first one to avoid a payload bloat
            "properties": {
                key: person.properties[key]
                for key in ["email", "name", "username"]
                if key in person.properties and key not in restricted
            },
        }

    @extend_schema_field(ElementSerializer(many=True))
    def get_elements(self, event):
        if not event["elements_chain"]:
            return []
        return ElementSerializer(chain_to_elements(event["elements_chain"]), many=True).data

    @extend_schema_field(serializers.CharField())
    def get_elements_chain(self, event):
        return event["elements_chain"]


def get_agg_event_count_for_teams(team_ids: list[Union[str, int]]) -> int:
    events_table = EVENTS_QUERY_TABLE()
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM {events_table}
        WHERE team_id IN (%(team_id_clause)s)
    """.format(events_table=events_table),
        {"team_id_clause": team_ids},
    )[0][0]
    return result


def get_agg_events_with_groups_count_for_teams_and_period(
    team_ids: list[Union[str, int]], begin: datetime, end: datetime
) -> int:
    events_table = EVENTS_QUERY_TABLE()
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM {events_table}
        WHERE team_id IN (%(team_id_clause)s)
        AND timestamp between %(begin)s AND %(end)s
        AND ($group_0 != '' OR $group_1 != '' OR $group_2 != '' OR $group_3 != '' OR $group_4 != '')
    """.format(events_table=events_table),
        {"team_id_clause": team_ids, "begin": begin, "end": end},
    )[0][0]
    return result


def get_event_count_for_team(team_id: Union[str, int]) -> int:
    events_table = EVENTS_QUERY_TABLE()
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM {events_table}
        WHERE team_id = %(team_id)s
    """.format(events_table=events_table),
        {"team_id": str(team_id)},
    )[0][0]
    return result


def get_event_count() -> int:
    """
    ```SELECT count(1) as count FROM events``` is too slow on cloud
    """
    events_data_table = EVENTS_INSERT_DATA_TABLE()
    result = sync_execute(
        """
        SELECT sum(rows) FROM system.parts WHERE (active = 1) AND (table = %(events_data_table)s)
    """,
        {"events_data_table": events_data_table},
    )[0][0]
    return result


def get_event_count_for_last_month() -> int:
    events_table = EVENTS_QUERY_TABLE()
    result = sync_execute(
        """
        -- count of events last month
        SELECT
        COUNT(1) freq
        FROM {events_table}
        WHERE
        toStartOfMonth(timestamp) = toStartOfMonth(date_sub(MONTH, 1, now()))
    """.format(events_table=events_table)
    )[0][0]
    return result


def get_event_count_month_to_date() -> int:
    events_table = EVENTS_QUERY_TABLE()
    result = sync_execute(
        """
        -- count of events month to date
        SELECT
        COUNT(1) freq
        FROM {events_table}
        WHERE toStartOfMonth(timestamp) = toStartOfMonth(now());
    """.format(events_table=events_table)
    )[0][0]
    return result
