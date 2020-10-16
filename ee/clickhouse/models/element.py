import datetime
import json
import re
from datetime import timezone
from typing import List, Optional
from uuid import UUID

from django.utils.timezone import now
from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from ee.kafka.client import ClickhouseProducer
from ee.kafka.topics import KAFKA_ELEMENTS
from posthog.cache import get_cached_value, set_cached_value
from posthog.models.element import Element
from posthog.models.element_group import hash_elements
from posthog.models.team import Team
from posthog.models.utils import UUIDT

chain_to_elements_regex = re.compile(
    r"(?P<tag_name>^[a-zA-Z\-]*)|\.*(?P<class>.*?)[\.|\:]|(?P<attribute>(?P<key>.*?)\=\"(?P<value>.*?[^\\])\")",
    re.MULTILINE,
)

# Below splits all elements by ;, while ignoring escaped quotes and semicolons within quotes
split_chain_regex = re.compile(r'(?:[^\s;"]|"(?:\\.|[^"])*")+')


def _escape(input: str) -> str:
    return input.replace('"', r"\"")


def elements_to_string(elements: List[Element],) -> str:
    ret = []
    for element in elements:
        el_string = ""
        if element.tag_name:
            el_string += element.tag_name
        if element.attr_class:
            for single_class in sorted(element.attr_class):
                el_string += ".{}".format(single_class)
        attributes = {
            **({"text": element.text} if element.text else {}),
            "nth-child": element.nth_child or 0,
            "nth-of-type": element.nth_of_type or 0,
            **({"href": element.href} if element.href else {}),
            **({"attr_id": element.attr_id} if element.attr_id else {}),
            **element.attributes,
        }
        attributes = {_escape(key): _escape(str(value)) for key, value in sorted(attributes.items())}
        el_string += ":"
        el_string += "".join(['{}="{}"'.format(key, value) for key, value in attributes.items()])
        ret.append(el_string)
    return ";".join(ret)


def chain_to_elements(chain: str) -> List[Element]:
    elements = []
    for idx, el_string in enumerate(re.findall(split_chain_regex, chain)):
        parsed = re.finditer(chain_to_elements_regex, el_string)
        element = Element(order=idx)
        for ii in parsed:
            item = ii.groupdict()
            if item["tag_name"]:
                element.tag_name = item["tag_name"]
            elif item["class"]:
                if not element.attr_class:
                    element.attr_class = []
                element.attr_class.append(item["class"])
            elif item["key"] == "href":
                element.href = item["value"]
            elif item["key"] == "nth-child":
                element.nth_child = int(item["value"])
            elif item["key"] == "nth-of-type":
                element.nth_of_type = int(item["value"])
            elif item["key"] == "text":
                element.text = item["value"]
            elif item["key"] == "attr_id":
                element.attr_id = item["value"]
            elif item["key"]:
                element.attributes[item["key"]] = item["value"]

        elements.append(element)
    return elements
