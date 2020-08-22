import datetime
from numbers import Number
from typing import Dict, Optional, Union

from celery import shared_task
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.core import serializers
from django.db import IntegrityError
from sentry_sdk import capture_exception

from posthog.models import Element, Event, Person, Team


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
        # Catch race case when somebody already added this distinct_id between .get and .add_distinct_id
        except IntegrityError:
            if retry_if_failed:  # run everything again to merge the users if needed
                _alias(previous_distinct_id, distinct_id, team_id, False)
        return

    if not old_person and new_person:
        try:
            new_person.add_distinct_id(previous_distinct_id)
        # Catch race case when somebody already added this distinct_id between .get and .add_distinct_id
        except IntegrityError:
            if retry_if_failed:  # run everything again to merge the users if needed
                _alias(previous_distinct_id, distinct_id, team_id, False)
        return

    if not old_person and not new_person:
        try:
            Person.objects.create(
                team_id=team_id, distinct_ids=[str(distinct_id), str(previous_distinct_id)],
            )
        # Catch race condition where in between getting and creating, another request already created this user.
        except IntegrityError:
            if retry_if_failed:
                # try once more, probably one of the two persons exists now
                _alias(previous_distinct_id, distinct_id, team_id, False)
        return

    if old_person and new_person and old_person != new_person:
        new_person.merge_people([old_person])


def _store_names_and_properties(team: Team, event: str, properties: Dict) -> None:
    # In _capture we only prefetch a couple of fields in Team to avoid fetching too much data
    save = False
    if event not in team.event_names:
        save = True
        team.event_names.append(event)
    for key in properties.keys():
        if key not in team.event_properties:
            team.event_properties.append(key)
            save = True
        if isinstance(key, Number) and key not in team.event_properties_numerical:
            team.event_properties_numerical.append(key)
            save = True
    if save:
        team.save()


def _capture(
    ip: str,
    site_url: str,
    team_id: int,
    event: str,
    distinct_id: str,
    properties: Dict,
    timestamp: Union[datetime.datetime, str],
) -> None:
    elements = properties.get("$elements")
    elements_list = None
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

    Event.objects.create(
        event=event,
        distinct_id=distinct_id,
        properties=properties,
        team=team,
        site_url=site_url,
        **({"timestamp": timestamp} if timestamp else {}),
        **({"elements": elements_list} if elements_list else {})
    )
    _store_names_and_properties(team=team, event=event, properties=properties)

    if not Person.objects.distinct_ids_exist(team_id=team_id, distinct_ids=[str(distinct_id)]):
        # Catch race condition where in between getting and creating, another request already created this user.
        try:
            Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
        except IntegrityError:
            pass


def _update_person_properties(team_id: int, distinct_id: str, properties: Dict) -> None:
    try:
        person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=str(distinct_id))
    except Person.DoesNotExist:
        try:
            person = Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
        # Catch race condition where in between getting and creating, another request already created this user.
        except:
            person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=str(distinct_id))
    person.properties.update(properties)
    person.save()


def _set_is_identified(team_id: int, distinct_id: str) -> None:
    try:
        person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=str(distinct_id))
    except Person.DoesNotExist:
        try:
            person = Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
        # Catch race condition where in between getting and creating, another request already created this user.
        except:
            person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=str(distinct_id))
    if not person.is_identified:
        person.is_identified = True
        person.save()


def _handle_timestamp(data: dict, now: str, sent_at: Optional[str]) -> Union[datetime.datetime, str]:
    if data.get("timestamp"):
        if sent_at:
            # sent_at - timestamp == now - x
            # x = now + (timestamp - sent_at)
            try:
                # timestamp and sent_at must both be in the same format: either both with or both without timezones
                # otherwise we can't get a diff to add to now
                return parser.isoparse(now) + (parser.isoparse(data["timestamp"]) - parser.isoparse(sent_at))
            except TypeError as e:
                capture_exception(e)

        return data["timestamp"]
    now_datetime = parser.parse(now)
    if data.get("offset"):
        return now_datetime - relativedelta(microseconds=data["offset"] * 1000)
    return now_datetime


@shared_task
def process_event(
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

    _capture(
        ip=ip,
        site_url=site_url,
        team_id=team_id,
        event=data["event"],
        distinct_id=distinct_id,
        properties=data.get("properties", data.get("$set", {})),
        timestamp=_handle_timestamp(data, now, sent_at),
    )
