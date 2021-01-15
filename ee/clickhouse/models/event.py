import json
import uuid
from typing import Dict, List, Optional, Tuple, Union

import celery
import pytz
from dateutil.parser import isoparse
from django.utils import timezone
from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.element import chain_to_elements, elements_to_string
from ee.clickhouse.sql.events import GET_EVENTS_BY_TEAM_SQL, GET_EVENTS_SQL, INSERT_EVENT_SQL
from ee.idl.gen import events_pb2
from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_EVENTS
from posthog.models.action_step import ActionStep
from posthog.models.element import Element
from posthog.models.person import Person
from posthog.models.team import Team


def create_event(
    event_uuid: uuid.UUID,
    event: str,
    team: Team,
    distinct_id: str,
    timestamp: Optional[Union[timezone.datetime, str]] = None,
    properties: Optional[Dict] = {},
    elements: Optional[List[Element]] = None,
    site_url: Optional[str] = None,
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

    pb_event = events_pb2.Event()
    pb_event.uuid = str(event_uuid)
    pb_event.event = event
    pb_event.properties = json.dumps(properties)
    pb_event.timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
    pb_event.team_id = team.pk
    pb_event.distinct_id = str(distinct_id)
    pb_event.elements_chain = elements_chain
    pb_event.created_at = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")

    p = ClickhouseProducer()

    p.produce_proto(sql=INSERT_EVENT_SQL, topic=KAFKA_EVENTS, data=pb_event)

    if team.slack_incoming_webhook or team.organization.is_feature_available("zapier"):
        # Do a little bit of pre-filtering
        if event in ActionStep.objects.filter(action__team_id=team.pk, action__post_to_slack=True).values_list(
            "event", flat=True
        ):
            try:
                celery.current_app.send_task(
                    "ee.tasks.webhooks_ee.post_event_to_webhook_ee",
                    (
                        {
                            "event": event,
                            "properties": properties,
                            "distinct_id": distinct_id,
                            "timestamp": timestamp,
                            "elements_list": elements,
                        },
                        team.pk,
                        site_url,
                    ),
                )
            except:
                pass

    return str(event_uuid)


def get_events():
    events = sync_execute(GET_EVENTS_SQL)
    return ClickhouseEventSerializer(events, many=True, context={"elements": None, "people": None}).data


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
            return event[5]
        return self.context["people"][event[5]].properties.get("email", event[5])

    def get_elements(self, event):
        if not event[6]:
            return []
        return ElementSerializer(chain_to_elements(event[6]), many=True).data

    def get_elements_chain(self, event):
        return event[6]


def determine_event_conditions(
    conditions: Dict[str, Union[str, List[str]]], long_date_from: bool = False
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
            distinct_ids = Person.objects.filter(pk=v)[0].distinct_ids
            distinct_ids = [distinct_id.__str__() for distinct_id in distinct_ids]
            params.update({"distinct_ids": distinct_ids})
        elif k == "distinct_id":
            result += "AND distinct_id = %(distinct_id)s"
            params.update({"distinct_id": v})
        elif k == "event":
            result += "AND event = %(event)s"
            params.update({"event": v})
    return result, params
