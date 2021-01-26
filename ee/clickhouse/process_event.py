import datetime
import json
from typing import Dict, Optional, Sequence
from uuid import UUID

import statsd
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.utils import IntegrityError
from sentry_sdk import capture_exception

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.kafka_client.client import KafkaProducer
from posthog.ee import is_ee_enabled
from posthog.models.element import Element
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.tasks.process_event import handle_identify_or_alias, sanitize_event_name, store_names_and_properties

if settings.STATSD_HOST is not None:
    statsd.Connection.set_defaults(host=settings.STATSD_HOST, port=settings.STATSD_PORT)


def _capture_ee(
    event_uuid: UUID,
    person_uuid: UUID,
    ip: str,
    site_url: str,
    team_id: int,
    event: str,
    distinct_id: str,
    properties: Dict,
    timestamp: datetime.datetime,
) -> None:
    elements = properties.get("$elements")
    elements_list = []
    if elements:
        del properties["$elements"]
        elements_list = [
            Element(
                text=el["$el_text"][0:400] if el.get("$el_text") else None,
                tag_name=el["tag_name"],
                href=el["attr__href"][0:2048] if el.get("attr__href") else None,
                attr_class=el["attr__class"].split(" ") if el.get("attr__class") else None,
                attr_id=el.get("attr__id"),
                nth_child=el.get("nth_child"),
                nth_of_type=el.get("nth_of_type"),
                attributes={key: value for key, value in el.items() if key.startswith("attr__")},
            )
            for index, el in enumerate(elements)
        ]

    team = Team.objects.select_related("organization").get(pk=team_id)

    if not team.anonymize_ips and "$ip" not in properties:
        properties["$ip"] = ip

    event = sanitize_event_name(event)
    store_names_and_properties(team=team, event=event, properties=properties)

    if not Person.objects.distinct_ids_exist(team_id=team_id, distinct_ids=[str(distinct_id)]):
        # Catch race condition where in between getting and creating,
        # another request already created this user
        try:
            Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
        except IntegrityError:
            pass

    # # determine create events
    create_event(
        event_uuid=event_uuid,
        event=event,
        properties=properties,
        timestamp=timestamp,
        team=team,
        distinct_id=distinct_id,
        elements=elements_list,
        site_url=site_url,
    )


def handle_timestamp(data: dict, now: datetime.datetime, sent_at: Optional[datetime.datetime]) -> datetime.datetime:
    if data.get("timestamp"):
        if sent_at:
            # sent_at - timestamp == now - x
            # x = now + (timestamp - sent_at)
            try:
                # timestamp and sent_at must both be in the same format: either both with or both without timezones
                # otherwise we can't get a diff to add to now
                return now + (parser.isoparse(data["timestamp"]) - sent_at)
            except TypeError as e:
                capture_exception(e)
        return parser.isoparse(data["timestamp"])
    now_datetime = now
    if data.get("offset"):
        return now_datetime - relativedelta(microseconds=data["offset"] * 1000)
    return now_datetime


if is_ee_enabled():

    def process_event_ee(
        distinct_id: str,
        ip: str,
        site_url: str,
        data: dict,
        team_id: int,
        now: datetime.datetime,
        sent_at: Optional[datetime.datetime],
        event_uuid: UUIDT,
    ) -> None:
        timer = statsd.Timer("%s_posthog_cloud" % (settings.STATSD_PREFIX,))
        timer.start()
        properties = data.get("properties", {})
        if data.get("$set"):
            properties["$set"] = data["$set"]
        if data.get("$set_once"):
            properties["$set_once"] = data["$set_once"]

        person_uuid = UUIDT()
        ts = handle_timestamp(data, now, sent_at)
        handle_identify_or_alias(data["event"], properties, distinct_id, team_id)

        if data["event"] == "$snapshot":
            create_session_recording_event(
                uuid=event_uuid,
                team_id=team_id,
                distinct_id=distinct_id,
                session_id=properties["$session_id"],
                snapshot_data=properties["$snapshot_data"],
                timestamp=ts,
            )
            return

        _capture_ee(
            event_uuid=event_uuid,
            person_uuid=person_uuid,
            ip=ip,
            site_url=site_url,
            team_id=team_id,
            event=data["event"],
            distinct_id=distinct_id,
            properties=properties,
            timestamp=ts,
        )
        timer.stop("process_event_ee")


else:

    def process_event_ee(
        distinct_id: str,
        ip: str,
        site_url: str,
        data: dict,
        team_id: int,
        now: datetime.datetime,
        sent_at: Optional[datetime.datetime],
        event_uuid: UUIDT,
    ) -> None:
        # Noop if ee is not enabled
        return


def log_event(
    distinct_id: str,
    ip: str,
    site_url: str,
    data: dict,
    team_id: int,
    now: datetime.datetime,
    sent_at: Optional[datetime.datetime],
    event_uuid: UUIDT,
    *,
    topics: Sequence[str],
) -> None:
    if settings.DEBUG:
        print(f'Logging event {data["event"]} to Kafka topics {" and ".join(topics)}')
    producer = KafkaProducer()
    data = {
        "uuid": str(event_uuid),
        "distinct_id": distinct_id,
        "ip": ip,
        "site_url": site_url,
        "data": json.dumps(data),
        "team_id": team_id,
        "now": now.isoformat(),
        "sent_at": sent_at.isoformat() if sent_at else "",
    }
    for topic in topics:
        producer.produce(topic=topic, data=data)
