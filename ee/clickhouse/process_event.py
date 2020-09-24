import datetime
from typing import Dict, List, Optional, Union

from celery import shared_task
from django.db import IntegrityError

from ee.clickhouse.models.element import create_elements
from ee.clickhouse.models.event import create_event
from posthog.ee import check_ee_enabled
from posthog.models.element import Element
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.tasks.process_event import handle_timestamp, store_names_and_properties


def _capture_ee(
    ip: str,
    site_url: str,
    team_id: int,
    event: str,
    distinct_id: str,
    properties: Dict,
    timestamp: Union[datetime.datetime, str],
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
                order=index,
            )
            for index, el in enumerate(elements)
        ]

    team = Team.objects.only("slack_incoming_webhook", "event_names", "event_properties", "anonymize_ips").get(
        pk=team_id
    )

    if not team.anonymize_ips:
        properties["$ip"] = ip

    store_names_and_properties(team=team, event=event, properties=properties)

    # determine/create elements
    element_hash = create_elements(elements_list, team)

    # # determine create events
    create_event(
        event=event,
        properties=properties,
        timestamp=timestamp,
        team=team,
        element_hash=element_hash,
        distinct_id=distinct_id,
    )


if check_ee_enabled():

    @shared_task
    def process_event_ee(
        distinct_id: str, ip: str, site_url: str, data: dict, team_id: int, now: str, sent_at: Optional[str],
    ) -> None:
        properties = data.get("properties", data.get("$set", {}))
        _capture_ee(
            ip=ip,
            site_url=site_url,
            team_id=team_id,
            event=data["event"],
            distinct_id=distinct_id,
            properties=properties,
            timestamp=handle_timestamp(data, now, sent_at),
        )


else:

    @shared_task
    def process_event_ee(*args, **kwargs) -> None:
        # Noop if ee is not enabled
        return
