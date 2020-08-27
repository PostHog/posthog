import datetime
from typing import Dict, List, Optional, Union

from celery import shared_task
from django.db import IntegrityError

from ee.clickhouse.models.element import create_elements
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import attach_distinct_ids, create_person_with_distinct_id
from posthog.models.element import Element
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.tasks.process_event import check_and_create_person, handle_timestamp, store_names_and_properties


def _alias(previous_distinct_id: str, distinct_id: str, team_id: int, retry_if_failed: bool = True,) -> None:
    old_person: Optional[Person] = None
    new_person: Optional[Person] = None

    try:
        old_person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=previous_distinct_id)
    except Person.DoesNotExist:
        pass

    try:
        new_person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=distinct_id)
    except Person.DoesNotExist:
        pass

    if old_person and not new_person:
        try:
            old_person.add_distinct_id(distinct_id)
            attach_distinct_ids(old_person.pk, [distinct_id], team_id)
        # Catch race case when somebody already added this distinct_id between .get and .add_distinct_id
        except IntegrityError:
            if retry_if_failed:  # run everything again to merge the users if needed
                _alias(previous_distinct_id, distinct_id, team_id, False)
        return

    if not old_person and new_person:
        try:
            new_person.add_distinct_id(previous_distinct_id)
            attach_distinct_ids(new_person.pk, [previous_distinct_id], team_id)
        # Catch race case when somebody already added this distinct_id between .get and .add_distinct_id
        except IntegrityError:
            if retry_if_failed:  # run everything again to merge the users if needed
                _alias(previous_distinct_id, distinct_id, team_id, False)
        return

    if not old_person and not new_person:
        try:
            person = Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id), str(previous_distinct_id)],)
            create_person_with_distinct_id(
                person_id=person.pk, team_id=team_id, distinct_ids=[str(distinct_id), str(previous_distinct_id)],
            )
        # Catch race condition where in between getting and creating, another request already created this user.
        except IntegrityError:
            if retry_if_failed:
                # try once more, probably one of the two persons exists now
                _alias(previous_distinct_id, distinct_id, team_id, False)
        return

    if old_person and new_person and old_person != new_person:
        new_person.merge_people([old_person])


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

    # # check/create persondistinctid
    person = check_and_create_person(team_id=team.pk, distinct_id=distinct_id)
    if person:
        create_person_with_distinct_id(person_id=person.id, distinct_ids=[distinct_id], team_id=team.pk)


def _update_person_properties(team_id: int, distinct_id: str, properties: Dict) -> None:
    try:
        person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=str(distinct_id))
    except Person.DoesNotExist:
        try:
            person = Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
            create_person_with_distinct_id(person.pk, [distinct_id], team_id)
        # Catch race condition where in between getting and creating, another request already created this person
        except:
            person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=str(distinct_id))
    person.properties.update(properties)
    person.save()

    pass


def _set_is_identified(team_id: int, distinct_id: str, is_identified: bool = True) -> None:
    try:
        person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=str(distinct_id))
    except Person.DoesNotExist:
        try:
            person = Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
            create_person_with_distinct_id(person.pk, [distinct_id], team_id)
        # Catch race condition where in between getting and creating, another request already created this person
        except:
            person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=str(distinct_id))
    if not person.is_identified:
        person.is_identified = is_identified
        person.save()


@shared_task
def process_event_ee(
    distinct_id: str, ip: str, site_url: str, data: dict, team_id: int, now: str, sent_at: Optional[str],
) -> None:
    if data["event"] == "$create_alias":
        _alias(
            previous_distinct_id=data["properties"]["alias"], distinct_id=distinct_id, team_id=team_id,
        )
    elif data["event"] == "$identify":
        _set_is_identified(team_id=team_id, distinct_id=distinct_id)
        if data.get("properties") and data["properties"].get("$anon_distinct_id"):
            _alias(
                previous_distinct_id=data["properties"]["$anon_distinct_id"], distinct_id=distinct_id, team_id=team_id,
            )
        if data.get("$set"):
            _update_person_properties(team_id=team_id, distinct_id=distinct_id, properties=data["$set"])

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
