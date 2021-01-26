import datetime
import json
from numbers import Number
from typing import Any, Dict, Optional, Tuple, Union

import posthoganalytics
from celery import shared_task
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.db import IntegrityError
from sentry_sdk import capture_exception

from posthog.models import Element, Event, Person, SessionRecordingEvent, Team


def _alias(previous_distinct_id: str, distinct_id: str, team_id: int, retry_if_failed: bool = True,) -> None:
    old_person: Optional[Person] = None
    new_person: Optional[Person] = None

    try:
        old_person = Person.objects.get(
            team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id=previous_distinct_id
        )
    except Person.DoesNotExist:
        pass

    try:
        new_person = Person.objects.get(
            team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id=distinct_id
        )
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


def sanitize_event_name(event: Any) -> str:
    if isinstance(event, str):
        return event[0:200]
    else:
        try:
            return json.dumps(event)[0:200]
        except TypeError:
            return str(event)[0:200]


def store_names_and_properties(team: Team, event: str, properties: Dict) -> None:
    # In _capture we only prefetch a couple of fields in Team to avoid fetching too much data
    save = False
    if not team.ingested_event:
        # First event for the team captured
        for user in team.organization.members.all():
            posthoganalytics.capture(user.distinct_id, "first team event ingested", {"team": str(team.uuid)})

        team.ingested_event = True
        save = True
    if event not in team.event_names:
        save = True
        team.event_names.append(event)
        team.event_names_with_usage.append({"event": event, "usage_count": None, "volume": None})
    for key, value in properties.items():
        if key not in team.event_properties:
            team.event_properties.append(key)
            team.event_properties_with_usage.append({"key": key, "usage_count": None, "volume": None})
            save = True
        if isinstance(value, Number) and key not in team.event_properties_numerical:
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
            )
            for index, el in enumerate(elements)
        ]

    team = Team.objects.only(
        "slack_incoming_webhook",
        "event_names",
        "event_properties",
        "event_names_with_usage",
        "event_properties_with_usage",
        "anonymize_ips",
        "ingested_event",
    ).get(pk=team_id)

    if not team.anonymize_ips and "$ip" not in properties:
        properties["$ip"] = ip

    event = sanitize_event_name(event)

    Event.objects.create(
        event=event,
        distinct_id=distinct_id,
        properties=properties,
        team=team,
        site_url=site_url,
        **({"timestamp": timestamp} if timestamp else {}),
        **({"elements": elements_list} if elements_list else {})
    )
    store_names_and_properties(team=team, event=event, properties=properties)
    if not Person.objects.distinct_ids_exist(team_id=team_id, distinct_ids=[str(distinct_id)]):
        # Catch race condition where in between getting and creating,
        # another request already created this user
        try:
            Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
        except IntegrityError:
            pass


def get_or_create_person(team_id: int, distinct_id: str) -> Tuple[Person, bool]:
    person: Person
    created = False

    if not Person.objects.distinct_ids_exist(team_id=team_id, distinct_ids=[str(distinct_id)]):
        try:
            person = Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
            created = True
        except IntegrityError:
            person = Person.objects.get(
                team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id=str(distinct_id)
            )
            created = False
    else:
        person = Person.objects.get(
            team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id=str(distinct_id)
        )
        created = False

    return person, created


def _update_person_properties(team_id: int, distinct_id: str, properties: Dict, set_once: bool = False) -> None:
    try:
        person = Person.objects.get(
            team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id=str(distinct_id)
        )
    except Person.DoesNotExist:
        try:
            person = Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
        # Catch race condition where in between getting and creating, another request already created this person
        except Exception:
            person = Person.objects.get(
                team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id=str(distinct_id)
            )
    if set_once:
        # Set properties on a user record, only if they do not yet exist.
        # Unlike $set, this will not overwrite existing people property values.
        new_properties = properties.copy()
        new_properties.update(person.properties)
        person.properties = new_properties
    else:
        person.properties.update(properties)
    person.save()


def _set_is_identified(team_id: int, distinct_id: str, is_identified: bool = True) -> None:
    try:
        person = Person.objects.get(
            team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id=str(distinct_id)
        )
    except Person.DoesNotExist:
        try:
            person = Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
        # Catch race condition where in between getting and creating, another request already created this person
        except:
            person = Person.objects.get(
                team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id=str(distinct_id)
            )
    if not person.is_identified:
        person.is_identified = is_identified
        person.save()


def _store_session_recording_event(
    team_id: int, distinct_id: str, session_id: str, timestamp: Union[datetime.datetime, str], snapshot_data: dict
) -> None:
    SessionRecordingEvent.objects.create(
        team_id=team_id,
        distinct_id=distinct_id,
        session_id=session_id,
        timestamp=timestamp,
        snapshot_data=snapshot_data,
    )


def handle_timestamp(data: dict, now: str, sent_at: Optional[str]) -> datetime.datetime:
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
        return parser.isoparse(data["timestamp"])
    now_datetime = parser.parse(now)
    if data.get("offset"):
        return now_datetime - relativedelta(microseconds=data["offset"] * 1000)
    return now_datetime


def handle_identify_or_alias(event: str, properties: dict, distinct_id: str, team_id: int) -> None:
    if event == "$create_alias":
        _alias(
            previous_distinct_id=properties["alias"], distinct_id=distinct_id, team_id=team_id,
        )
    elif event == "$identify":
        if properties.get("$anon_distinct_id"):
            _alias(
                previous_distinct_id=properties["$anon_distinct_id"], distinct_id=distinct_id, team_id=team_id,
            )
        if properties.get("$set"):
            _update_person_properties(team_id=team_id, distinct_id=distinct_id, properties=properties["$set"])
        if properties.get("$set_once"):
            _update_person_properties(
                team_id=team_id, distinct_id=distinct_id, properties=properties["$set_once"], set_once=True
            )
        _set_is_identified(team_id=team_id, distinct_id=distinct_id)


@shared_task(name="posthog.tasks.process_event.process_event", ignore_result=True)
def process_event(
    distinct_id: str, ip: str, site_url: str, data: dict, team_id: int, now: str, sent_at: Optional[str],
) -> None:
    properties = data.get("properties", {})
    if data.get("$set"):
        properties["$set"] = data["$set"]
    if data.get("$set_once"):
        properties["$set_once"] = data["$set_once"]

    handle_identify_or_alias(data["event"], properties, distinct_id, team_id)

    if data["event"] == "$snapshot":
        _store_session_recording_event(
            team_id=team_id,
            distinct_id=distinct_id,
            session_id=data["properties"]["$session_id"],
            timestamp=handle_timestamp(data, now, sent_at),
            snapshot_data=data["properties"]["$snapshot_data"],
        )
        return

    _capture(
        ip=ip,
        site_url=site_url,
        team_id=team_id,
        event=data["event"],
        distinct_id=distinct_id,
        properties=properties,
        timestamp=handle_timestamp(data, now, sent_at),
    )
