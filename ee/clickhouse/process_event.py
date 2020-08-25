import json
from datetime import datetime
from typing import Dict, List, Union
from uuid import uuid4

from ee.clickhouse.client import ch_client
from posthog.models.element import Element
from posthog.models.element_group import hash_elements
from posthog.models.team import Team


# TODO: timestamp QA
# TODO: handle siteurl for action trigger
def capture_ee(
    event: str,
    distinct_id: str,
    properties: Dict,
    site_url: str,
    team: Team,
    timestamp: Union[datetime, str],
    elements: List,
) -> None:
    # determine/create elements
    element_hash = _create_elements(elements, team)

    # # determine create events
    _create_event(
        event=event,
        properties=properties,
        timestamp=timestamp,
        team=team,
        element_hash=element_hash,
        distinct_id=distinct_id,
    )

    # # check/create persondistinctid
    _check_person_distinct_ids(ids=[distinct_id], team=team)

    pass


INSERT_ELEMENT_GROUP_SQL = """
INSERT INTO elements_group SELECT '{id}', '{element_hash}', {team_id}
"""

INSERT_ELEMENTS_SQL = """
INSERT INTO elements SELECT 
    generateUUIDv4(), 
    '{text}',
    '{tag_name}',
    '{href}',
    '{attr_id}',
    {attr_class},
    {nth_child},
    {nth_of_type},
    '{attributes}',
    {order},
    {team_id},
    now(),
    '{group_id}'
"""


def _create_elements(elements: List[Element], team: Team) -> str:

    # create group
    element_hash = hash_elements(elements)
    group_id = uuid4()
    ch_client.execute(INSERT_ELEMENT_GROUP_SQL.format(id=group_id, element_hash=element_hash, team_id=team.pk))

    # create elements
    for element in elements:
        element_query = INSERT_ELEMENTS_SQL.format(
            text=element.text or "",
            tag_name=element.tag_name or "",
            href=element.href or "",
            attr_id=element.attr_id,
            attr_class=element.attr_class or [],
            nth_child=element.nth_child,
            nth_of_type=element.nth_of_type,
            attributes=json.dumps(element.attributes or {}),
            order=element.order,
            team_id=team.pk,
            group_id=group_id,
        )

        ch_client.execute(element_query)

    return element_hash


INSERT_EVENT_SQL = """
INSERT INTO events SELECT generateUUIDv4(), '{event}', '{properties}', parseDateTimeBestEffort('{timestamp}'), {team_id}, '{distinct_id}', '{element_hash}', now()
"""


def _create_event(
    event: str, properties: Dict, timestamp: Union[datetime, str], team: Team, element_hash: str, distinct_id: str
) -> None:
    query = INSERT_EVENT_SQL.format(
        event=event,
        properties=json.dumps(properties),
        timestamp=timestamp,
        team_id=team.pk,
        distinct_id=distinct_id,
        element_hash=element_hash,
    )
    ch_client.execute(query)


PERSON_DISTINCT_ID_EXISTS_SQL = """
SELECT count(*) FROM person_distinct_id inner join (SELECT arrayJoin({}) as distinct_id) as something ON something.distinct_id = person_distinct_id.distinct_id
"""

INSERT_PERSON_SQL = """
INSERT INTO person SELECT '{id}', now(), '{properties}', {team_id}
"""

INSERT_PERSON_DISTINCT_ID = """
INSERT INTO person_distinct_id SELECT generateUUIDv4(), '{distinct_id}', '{person_id}', {team_id}
"""


def _check_person_distinct_ids(ids: List[str], team=Team) -> None:
    if not bool(ch_client.execute(PERSON_DISTINCT_ID_EXISTS_SQL.format(ids))[0][0]):
        person_id = uuid4()
        query = INSERT_PERSON_SQL.format(id=person_id, properties=json.dumps({}), team_id=team.pk)
        ch_client.execute(query)
        for id in ids:
            ch_client.execute(INSERT_PERSON_DISTINCT_ID.format(distinct_id=id, person_id=person_id, team_id=team.pk))
