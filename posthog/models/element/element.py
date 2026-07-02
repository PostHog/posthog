import re
from collections.abc import Callable

from django.contrib.postgres.fields import ArrayField
from django.db import models


class Element(models.Model):
    USEFUL_ELEMENTS = ["a", "button", "input", "select", "textarea", "label"]
    text = models.CharField(max_length=10_000, null=True, blank=True)
    tag_name = models.CharField(max_length=1_000, null=True, blank=True)
    href = models.CharField(max_length=10_000, null=True, blank=True)
    attr_id = models.CharField(max_length=10_000, null=True, blank=True)
    attr_class = ArrayField(models.CharField(max_length=200, blank=True), null=True, blank=True)
    nth_child = models.IntegerField(null=True, blank=True)
    nth_of_type = models.IntegerField(null=True, blank=True)
    attributes = models.JSONField(default=dict)
    event = models.ForeignKey("Event", on_delete=models.CASCADE, null=True, blank=True)
    order = models.IntegerField(null=True, blank=True)
    group = models.ForeignKey("ElementGroup", on_delete=models.CASCADE, null=True, blank=True)


parse_attributes_regex = re.compile(r"(?P<attribute>(?P<key>.*?)\=\"(?P<value>.*?[^\\])\")", re.MULTILINE)

# Below splits all elements by ;, while ignoring escaped quotes and semicolons within quotes
split_chain_regex = re.compile(r'(?:[^\s;"]|"(?:\\.|[^"])*")+')

# Below splits the tag/classes from attributes
# Needs a regex because classes can have : too
split_class_attributes = re.compile(r"(.*?)($|:([a-zA-Z\-\_0-9]*=.*))")


def _escape(input: str) -> str:
    return input.replace('"', r"\"")


def elements_to_string(elements: list[Element]) -> str:
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


def chain_to_elements(chain: str) -> list[Element]:
    """
    Converts an elements chain string into a list of Element objects.
    """
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


_MAX_DATA_ATTRIBUTES = 50


def _glob_matcher(pattern: str) -> Callable[[str], bool]:
    """Returns a matcher for a glob pattern where each * matches any run of characters.
    Linear-time string scanning, never regex, so caller-supplied patterns can't trigger
    catastrophic backtracking."""
    head, *middle, tail = pattern.split("*")

    def matches(key: str) -> bool:
        if not key.startswith(head) or not key.endswith(tail):
            return False
        position = len(head)
        end = len(key) - len(tail)
        for segment in middle:
            found = key.find(segment, position, end)
            if found == -1:
                return False
            position = found + len(segment)
        return position <= end

    return matches


def build_attributes_filter(wanted_data_attributes: list[str]) -> Callable[[str], bool] | None:
    """
    Builds a matcher for attr__ keys matching the configured data attributes, mirroring the
    toolbar's matchesDataAttribute: keys carry an attr__ prefix and configured names may use
    * wildcards (e.g. data-*). Entries beyond the first 50 are ignored to bound per-key cost.
    Returns None when there is nothing to filter by.
    """
    entries = [attribute.strip() for attribute in wanted_data_attributes[:_MAX_DATA_ATTRIBUTES] if attribute.strip()]
    if not entries:
        return None

    exact_keys = frozenset(f"attr__{entry}" for entry in entries if "*" not in entry)
    glob_matchers = [_glob_matcher(f"attr__{entry}") for entry in entries if "*" in entry]

    def matches(key: str) -> bool:
        if key in exact_keys:
            return True
        for matcher in glob_matchers:
            if matcher(key):
                return True
        return False

    return matches


def chain_to_element_dicts(chain: str, attributes_filter: Callable[[str], bool] | None = None) -> list[dict]:
    """
    Converts an elements chain string into serialized element dicts, shaped exactly like
    ElementSerializer output but without instantiating Element models, so the elements API
    can serialize large pages cheaply. attributes_filter optionally restricts the attributes
    map to matching keys (see build_attributes_filter).
    """
    element_dicts: list[dict] = []
    for idx, el_string in enumerate(split_chain_regex.findall(chain)):
        el_string_match = split_class_attributes.search(el_string)
        tag_part = el_string_match.group(1) if el_string_match else ""
        attrs_part = el_string_match.group(3) if el_string_match else None

        element: dict = {
            "text": None,
            "tag_name": None,
            "attr_class": None,
            "href": None,
            "attr_id": None,
            "nth_child": None,
            "nth_of_type": None,
            "attributes": {},
            "order": idx,
        }

        if tag_part:
            tag_and_class = tag_part.split(".", 1)
            element["tag_name"] = tag_and_class[0]
            if len(tag_and_class) > 1:
                element["attr_class"] = [cl for cl in tag_and_class[1].split(".") if cl != ""]

        if attrs_part:
            for attribute_match in parse_attributes_regex.finditer(attrs_part):
                key = attribute_match.group("key")
                value = attribute_match.group("value")
                if key == "href":
                    element["href"] = value
                elif key == "nth-child":
                    element["nth_child"] = int(value)
                elif key == "nth-of-type":
                    element["nth_of_type"] = int(value)
                elif key == "text":
                    element["text"] = value
                elif key == "attr_id":
                    element["attr_id"] = value
                elif key:
                    if attributes_filter is None or attributes_filter(key):
                        element["attributes"][key] = value

        element_dicts.append(element)
    return element_dicts
