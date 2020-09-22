import json
from typing import List
from uuid import UUID, uuid4

from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.elements import GET_ALL_ELEMENTS_SQL, GET_ELEMENTS_BY_ELEMENTS_HASH_SQL, INSERT_ELEMENTS_SQL
from ee.kafka.client import KafkaProducer
from ee.kafka.topics import KAFKA_ELEMENTS
from posthog.cache import get_cached_value, set_cached_value
from posthog.models.element import Element
from posthog.models.element_group import hash_elements
from posthog.models.team import Team


def create_element(element: Element, team: Team, elements_hash: str) -> None:
    p = KafkaProducer()
    data = {
        "text": element.text or "",
        "tag_name": element.tag_name or "",
        "href": element.href or "",
        "attr_id": element.attr_id or "",
        "attr_class": element.attr_class or [],
        "nth_child": element.nth_child or 0,
        "nth_of_type": element.nth_of_type or 0,
        "attributes": json.dumps(element.attributes or {}),
        "order": element.order or 0,
        "team_id": team.pk,
        "elements_hash": elements_hash,
    }
    p.produce(topic=KAFKA_ELEMENTS, data=json.dumps(data))


def create_elements(elements: List[Element], team: Team, use_cache: bool = True) -> str:
    # create group
    for index, element in enumerate(elements):
        element.order = index
    elements_hash = hash_elements(elements)

    if use_cache and get_cached_value(team.pk, "elements/{}".format(elements_hash)):
        return elements_hash

    # create elements
    for index, element in enumerate(elements):
        create_element(element=element, team=team, elements_hash=elements_hash)

    if use_cache:
        set_cached_value(team.pk, "elements/{}".format(elements_hash), "1")

    return elements_hash


def get_elements_by_elements_hash(elements_hash: str, team_id: int):
    result = sync_execute(GET_ELEMENTS_BY_ELEMENTS_HASH_SQL, {"elements_hash": elements_hash, "team_id": team_id})
    return ClickhouseElementSerializer(result, many=True).data


def get_all_elements(final: bool = False):
    result = sync_execute(GET_ALL_ELEMENTS_SQL.format(final="FINAL" if final else ""))
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
    elements_hash = serializers.SerializerMethodField()

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
        return json.loads(element[8])

    def get_order(self, element):
        return element[9]

    def get_team_id(self, element):
        return element[10]

    def get_created_at(self, element):
        return element[11]

    def get_elements_hash(self, element):
        return element[12]
