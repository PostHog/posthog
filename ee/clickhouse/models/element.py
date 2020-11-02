import re
from typing import List

from posthog.models.element import Element

parse_attributes_regex = re.compile(r"(?P<attribute>(?P<key>.*?)\=\"(?P<value>.*?[^\\])\")", re.MULTILINE,)

# Below splits all elements by ;, while ignoring escaped quotes and semicolons within quotes
split_chain_regex = re.compile(r'(?:[^\s;"]|"(?:\\.|[^"])*")+')

# Below splits the tag/classes from attributes
# Needs a regex because classes can have : too
split_class_attributes = re.compile(r"(.*?)($|:([a-zA-Z\-\_0-9]*=.*))")


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
                el_string += ".{}".format(single_class.replace('"', ""))
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
        el_string_split = re.findall(split_class_attributes, el_string)[0]
        attributes = re.finditer(parse_attributes_regex, el_string_split[2]) if len(el_string_split) > 2 else []

        element = Element(order=idx)

        if el_string_split[0]:
            tag_and_class = el_string_split[0].split(".", 1)
            element.tag_name = tag_and_class[0]
            if len(tag_and_class) > 1:
                element.attr_class = [cl for cl in tag_and_class[1].split(".") if cl != ""]

        for ii in attributes:
            item = ii.groupdict()
            if item["key"] == "href":
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
