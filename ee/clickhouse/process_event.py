import datetime
import json
from typing import Dict, Optional
from uuid import UUID

from celery import shared_task
from django.db.utils import IntegrityError

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.kafka_client.client import KafkaProducer
from ee.kafka_client.topics import KAFKA_EVENTS_WAL
from posthog.ee import check_ee_enabled
from posthog.models.element import Element
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.tasks.process_event import handle_identify_or_alias, handle_timestamp, store_names_and_properties


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

    team = Team.objects.only("slack_incoming_webhook", "event_names", "event_properties", "anonymize_ips").get(
        pk=team_id
    )

    if not team.anonymize_ips and "$ip" not in properties:
        properties["$ip"] = ip

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
    )


if check_ee_enabled():

    @shared_task(name="ee.clickhouse.process_event.process_event_ee", ignore_result=True)
    def process_event_ee(
        distinct_id: str, ip: str, site_url: str, data: dict, team_id: int, now: str, sent_at: Optional[str],
    ) -> None:
        properties = data.get("properties", {})
        if data.get("$set"):
            properties["$set"] = data["$set"]

        person_uuid = UUIDT()
        event_uuid = UUIDT()
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


else:

    @shared_task(name="ee.clickhouse.process_event.process_event_ee", ignore_result=True)
    def process_event_ee(*args, **kwargs) -> None:
        # Noop if ee is not enabled
        return


@shared_task(name="process_event_ee", ignore_result=True)
def process_event_ee_deprecated(*args, **kwargs) -> None:
    process_event_ee(*args, **kwargs)


def log_event(
    distinct_id: str,
    ip: str,
    site_url: str,
    data: dict,
    team_id: int,
    now: datetime.datetime,
    sent_at: Optional[datetime.datetime],
) -> None:
    data = {
        "distinct_id": distinct_id,
        "ip": ip,
        "site_url": site_url,
        "data": json.dumps(data),
        "team_id": team_id,
        "now": now.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "sent_at": sent_at.strftime("%Y-%m-%d %H:%M:%S.%f") if sent_at else "",
    }
    p = KafkaProducer()
    p.produce(topic=KAFKA_EVENTS_WAL, data=data)
