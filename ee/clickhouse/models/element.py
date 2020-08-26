import json
from typing import List
from uuid import UUID, uuid4

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.elements import INSERT_ELEMENT_GROUP_SQL, INSERT_ELEMENTS_SQL
from posthog.models.element import Element
from posthog.models.element_group import hash_elements
from posthog.models.team import Team


def create_element_group(team: Team, element_hash: str, id: UUID = uuid4()) -> UUID:
    ch_client.execute(INSERT_ELEMENT_GROUP_SQL.format(id=id, element_hash=element_hash, team_id=team.pk))
    return id


def create_element(element: Element, team: Team, group_id: UUID) -> None:
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


def create_elements(elements: List[Element], team: Team) -> str:

    # create group
    element_hash = hash_elements(elements)
    group_id = create_element_group(element_hash=element_hash, team=team)

    # create elements
    for element in elements:
        create_element(element=element, team=team, group_id=group_id)

    return element_hash
