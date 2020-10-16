import datetime
from typing import Dict, Optional
from uuid import UUID

from celery import shared_task

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import emit_omni_person
from posthog.ee import check_ee_enabled
from posthog.models.element import Element
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.tasks.process_event import handle_timestamp, store_names_and_properties


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
    emit_omni_person(
        event_uuid=event_uuid,
        uuid=person_uuid,
        team_id=team_id,
        distinct_id=distinct_id,
        timestamp=timestamp,
        properties=properties,
    )


if check_ee_enabled():

    @shared_task
    def process_event_ee(
        distinct_id: str, ip: str, site_url: str, data: dict, team_id: int, now: str, sent_at: Optional[str],
    ) -> None:
        properties = data.get("properties", None)
        person_uuid = UUIDT()
        event_uuid = UUIDT()
        ts = handle_timestamp(data, now, sent_at)

        if data["event"] == "$create_alias":
            emit_omni_person(
                event_uuid=event_uuid,
                uuid=person_uuid,
                team_id=team_id,
                distinct_id=distinct_id,
                timestamp=ts,
                properties=properties,
            )
            emit_omni_person(
                event_uuid=event_uuid,
                uuid=person_uuid,
                team_id=team_id,
                distinct_id=properties["alias"],
                timestamp=ts,
                properties=properties,
            )
        elif data["event"] == "$identify":
            if properties and properties.get("$anon_distinct_id"):
                emit_omni_person(
                    event_uuid=event_uuid,
                    uuid=person_uuid,
                    team_id=team_id,
                    distinct_id=distinct_id,
                    timestamp=ts,
                    properties=properties,
                )
                emit_omni_person(
                    event_uuid=event_uuid,
                    uuid=person_uuid,
                    team_id=team_id,
                    distinct_id=properties["$anon_distinct_id"],
                    timestamp=ts,
                    properties=properties,
                )
            if data.get("$set"):
                emit_omni_person(
                    event_uuid=event_uuid,
                    uuid=person_uuid,
                    team_id=team_id,
                    distinct_id=distinct_id,
                    timestamp=ts,
                    properties=data["$set"],
                    is_identified=True,
                )

        properties = data.get("properties", data.get("$set", {}))
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

    @shared_task
    def process_event_ee(*args, **kwargs) -> None:
        # Noop if ee is not enabled
        return
