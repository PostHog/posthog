import json
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

import pytz
from dateutil.parser import isoparse
from django.utils import timezone
from rest_framework import serializers

from ee.clickhouse.models.element import chain_to_elements, elements_to_string
from ee.clickhouse.sql.events import BULK_INSERT_EVENT_SQL, GET_EVENTS_BY_TEAM_SQL, INSERT_EVENT_SQL
from posthog.client import sync_execute
from posthog.models.element import Element
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

    sync_execute(
        INSERT_EVENT_SQL(),
        {
            "uuid": str(event_uuid),
            "event": event,
            "properties": json.dumps(properties),
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "team_id": team.pk,
            "distinct_id": str(distinct_id),
            "elements_chain": elements_chain,
            "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        },
    )

    return str(event_uuid)


def bulk_create_events(events: List[Dict[str, Any]]):
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
            "(%(uuid_{i})s, %(event_{i})s, %(properties_{i})s, %(timestamp_{i})s, %(team_id_{i})s, %(distinct_id_{i})s, %(elements_chain_{i})s, %(created_at_{i})s, now(), 0)".format(
                i=index
            )
        )
        event = {
            "uuid": str(event["event_uuid"]) if event.get("event_uuid") else str(uuid.uuid4()),
            "event": event["event"],
            "properties": json.dumps(event["properties"]) if event.get("properties") else "{}",
            "timestamp": timestamp,
            "team_id": event["team"].pk if event.get("team") else event["team_id"],
            "distinct_id": str(event["distinct_id"]),
            "elements_chain": elements_chain,
            "created_at": timestamp,
        }

        params = {**params, **{"{}_{}".format(key, index): value for key, value in event.items()}}
    sync_execute(BULK_INSERT_EVENT_SQL() + ", ".join(inserts), params, flush=False)


def get_events_by_team(team_id: Union[str, int]):
    events = sync_execute(GET_EVENTS_BY_TEAM_SQL, {"team_id": str(team_id)})
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
        return str(event[0])

    def get_distinct_id(self, event):
        return event[5]

    def get_properties(self, event):
        if len(event) >= 10 and event[8] and event[9]:
            prop_vals = [res.strip('"') for res in event[9]]
            return dict(zip(event[8], prop_vals))
        else:
            # parse_constants gets called for any NaN, Infinity etc values
            # we just want those to be returned as None
            props = json.loads(event[2], parse_constant=lambda x: None)
            unpadded = {key: value.strip('"') if isinstance(value, str) else value for key, value in props.items()}
            return unpadded

    def get_event(self, event):
        return event[1]

    def get_timestamp(self, event):
        dt = event[3].replace(tzinfo=timezone.utc)
        return dt.astimezone().isoformat()

    def get_person(self, event):
        if not self.context.get("people") or event[5] not in self.context["people"]:
            return None

        person = self.context["people"][event[5]]
        return {
            "is_identified": person.is_identified,
            "distinct_ids": person.distinct_ids[:1],  # only send the first one to avoid a payload bloat
            "properties": {
                key: person.properties[key] for key in ["email", "name", "username"] if key in person.properties
            },
        }

    def get_elements(self, event):
        if not event[6]:
            return []
        return ElementSerializer(chain_to_elements(event[6]), many=True).data

    def get_elements_chain(self, event):
        return event[6]


def determine_event_conditions(
    team: Team, conditions: Dict[str, Union[str, List[str]]], long_date_from: bool
) -> Tuple[str, Dict]:
    result = ""
    params: Dict[str, Union[str, List[str]]] = {}
    for idx, (k, v) in enumerate(conditions.items()):
        if not isinstance(v, str):
            continue
        if k == "after" and not long_date_from:
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp > %(after)s"
            params.update({"after": timestamp})
        elif k == "before":
            timestamp = isoparse(v).strftime("%Y-%m-%d %H:%M:%S.%f")
            result += "AND timestamp < %(before)s"
            params.update({"before": timestamp})
        elif k == "person_id":
            result += """AND distinct_id IN (%(distinct_ids)s)"""
            person = Person.objects.filter(pk=v, team_id=team.pk).first()
            distinct_ids = person.distinct_ids if person is not None else []
            params.update({"distinct_ids": list(map(str, distinct_ids))})
        elif k == "distinct_id":
            result += "AND distinct_id = %(distinct_id)s"
            params.update({"distinct_id": v})
        elif k == "event":
            result += "AND event = %(event)s"
            params.update({"event": v})
    return result, params


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
