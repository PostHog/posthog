import json
from typing import List
from uuid import UUID, uuid4

from rest_framework import serializers

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.elements import (
    GET_ELEMENT_BY_GROUP_SQL,
    GET_ELEMENT_GROUP_BY_HASH_SQL,
    GET_ELEMENTS_SQL,
    INSERT_ELEMENT_GROUP_SQL,
    INSERT_ELEMENTS_SQL,
)
from posthog.models.element import Element
from posthog.models.element_group import hash_elements
from posthog.models.team import Team


def create_element_group(team: Team, element_hash: str) -> UUID:
    id = uuid4()
    ch_client.execute(INSERT_ELEMENT_GROUP_SQL, {"id": id, "element_hash": element_hash, "team_id": team.pk})
    return id


def create_element(element: Element, team: Team, group_id: UUID) -> None:
    ch_client.execute(
        INSERT_ELEMENTS_SQL,
        {
            "text": element.text or "",
            "tag_name": element.tag_name or "",
            "href": element.href or "",
            "attr_id": element.attr_id or "",
            "attr_class": element.attr_class or [],
            "nth_child": element.nth_child,
            "nth_of_type": element.nth_of_type,
            "attributes": json.dumps(element.attributes or {}),
            "order": element.order,
            "team_id": team.pk,
            "group_id": group_id,
        },
    )


def create_elements(elements: List[Element], team: Team) -> str:

    # create group
    element_hash = hash_elements(elements)
    group_id = create_element_group(element_hash=element_hash, team=team)

    # create elements
    for element in elements:
        create_element(element=element, team=team, group_id=group_id)

    return element_hash


async def get_element_group_by_hash(elements_hash: str):
    result = await ch_client.execute(GET_ELEMENT_GROUP_BY_HASH_SQL, {"elements_hash": elements_hash})
    return ClickhouseElementGroupSerializer(result, many=True).data


async def get_elements_by_group(group_id: UUID):
    result = await ch_client.execute(GET_ELEMENT_BY_GROUP_SQL, {"group_id": group_id})
    return ClickhouseElementSerializer(result, many=True).data


async def get_elements():
    result = await ch_client.execute(GET_ELEMENTS_SQL)
    return ClickhouseElementSerializer(result, many=True).data


class ClickhouseElementSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    text = serializers.SerializerMethodField()
    tag_name = serializers.SerializerMethodField()
    href = serializers.SerializerMethodField()
    attr_id = serializers.SerializerMethodField()
    attr_class = serializers.SerializerMethodField()
    nth_child = serializers.SerializerMethodField()
    nth_of_type = serializers.SerializerMethodField()
    attributes = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    group_id = serializers.SerializerMethodField()

    def get_id(self, element):
        return element[0]

    def get_text(self, element):
        return element[1]

    def get_tag_name(self, element):
        return element[2]

    def get_href(self, element):
        return element[3]

    def get_attr_id(self, element):
        return element[4]

    def get_attr_class(self, element):
        return element[5]

    def get_nth_child(self, element):
        return element[6]

    def get_nth_of_type(self, element):
        return element[7]

    def get_attributes(self, element):
        return element[8]

    def get_order(self, element):
        return element[9]

    def get_team_id(self, element):
        return element[10]

    def get_created_at(self, element):
        return element[11]

    def get_group_id(self, element):
        return element[12]


class ClickhouseElementGroupSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    elements_hash = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()

    def get_id(self, element_group):
        return element_group[0]

    def get_elements_hash(self, element_group):
        return element_group[1]

    def get_team_id(self, element_group):
        return element_group[2]
