from celery import shared_task
from posthog.models import Person, Element, Event, Team
from typing import Union, Dict
from dateutil.relativedelta import relativedelta
from dateutil import parser

from django.db import IntegrityError
import datetime

def _alias(distinct_id: str, new_distinct_id: str, team_id: int) -> None:
    try:
        person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=distinct_id)
    except Person.DoesNotExist:
        # no reason to alias if it doesn't exist
        # mostly happens if someone calls identify before the user has done anything
        return
    try:
        person.add_distinct_id(new_distinct_id)
    except IntegrityError:
        # IntegrityError means a person with new_distinct_id already exists
        # That can either mean `person` already has that distinct_id, in which case we do nothing
        # OR it means there is _another_ Person with that distinct _id, in which case we want to remove that person
        # and add that distinct ID to `person`
        previous_person = Person.objects.filter(team_id=team_id, persondistinctid__distinct_id=new_distinct_id).exclude(pk=person.id)
        if previous_person.exists():
            person.properties.update(previous_person.first().properties) # type: ignore
            previous_person.delete()
            person.add_distinct_id(new_distinct_id)
            person.save()

def _store_names_and_properties(team_id: int, event: str, properties: Dict) -> None:
    team = Team.objects.get(pk=team_id)
    save = False
    if event not in team.event_names:
        save = True
        team.event_names.append(event)
    for key in properties.keys():
        if key not in team.event_properties:
            team.event_properties.append(key)
            save = True
    if save:
        team.save()

def _capture(ip: str, site_url: str, team_id: int, event: str, distinct_id: str, properties: Dict, timestamp: Union[datetime.datetime, str]) -> None:
    elements = properties.get('$elements')
    elements_list = None
    if elements:
        del properties['$elements']
        elements_list = [
            Element(
                text=el.get('$el_text'),
                tag_name=el['tag_name'],
                href=el.get('attr__href'),
                attr_class=el['attr__class'].split(' ') if el.get('attr__class') else None,
                attr_id=el.get('attr__id'),
                nth_child=el.get('nth_child'),
                nth_of_type=el.get('nth_of_type'),
                attributes={key: value for key, value in el.items() if key.startswith('attr__')},
                order=index
            ) for index, el in enumerate(elements)
        ]
    properties["$ip"] = ip

    Event.objects.create(
        event=event,
        distinct_id=distinct_id,
        properties=properties,
        team_id=team_id,
        site_url=site_url,
        **({'timestamp': timestamp} if timestamp else {}),
        **({'elements': elements_list} if elements_list else {})
    )
    _store_names_and_properties(team_id=team_id, event=event, properties=properties)
    # try to create a new person
    try:
        Person.objects.create(team_id=team_id, distinct_ids=[str(distinct_id)])
    except IntegrityError: 
        pass # person already exists, which is fine

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

def _handle_timestamp(data: dict, now: str) -> Union[datetime.datetime, str]:
    if data.get('timestamp'):
        return data['timestamp']
    now_datetime = parser.isoparse(now)
    if data.get('offset'):
        return now_datetime - relativedelta(microseconds=data['offset'] * 1000)
    return now_datetime

@shared_task
def process_event(distinct_id: str, ip: str, site_url: str, data: dict, team_id: int, now: str) -> None:
    if data['event'] == '$create_alias':
        _alias(distinct_id=data['properties']['alias'], new_distinct_id=distinct_id, team_id=team_id)

    if data['event'] == '$identify' and data.get('properties') and data['properties'].get('$anon_distinct_id'):
        _alias(distinct_id=data['properties']['$anon_distinct_id'], new_distinct_id=distinct_id, team_id=team_id)

    if data['event'] == '$identify' and data.get('$set'):
        _update_person_properties(team_id=team_id, distinct_id=distinct_id, properties=data['$set'])

    _capture(
        ip=ip,
        site_url=site_url,
        team_id=team_id,
        event=data['event'],
        distinct_id=distinct_id,
        properties=data.get('properties', data.get('$set', {})),
        timestamp=_handle_timestamp(data, now)
    )