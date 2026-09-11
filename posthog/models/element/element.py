from collections.abc import Callable

from django.contrib.postgres.fields import ArrayField
from django.db import models

import re2


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


parse_attributes_regex = re2.compile(r'(?P<attribute>(?P<key>.*?)="(?P<value>.*?[^\\])")')

# Below splits all elements by ;, while ignoring escaped quotes and semicolons within quotes
# RE2's \s is ASCII-only; element chains use Python's Unicode whitespace rules.
_PYTHON_WHITESPACE = r"\x09-\x0d\x1c-\x20\x85\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}"
split_chain_regex = re2.compile(r"(?:[^" + _PYTHON_WHITESPACE + r';"]|"(?:\\.|[^"])*")+')

# Below splits the tag/classes from attributes
# Needs a regex because classes can have : too
split_class_attributes = re2.compile(r"(.*?)($|:([a-zA-Z\-_0-9]*=.*))")


def _regex_input(source: str) -> str:
    # RE2 rejects lone surrogates. Match an equivalent character, then slice the original text.
    return source.encode("utf-8", errors="replace").decode("utf-8")


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
    for idx, chain_match in enumerate(split_chain_regex.finditer(_regex_input(chain))):
        el_string = chain[chain_match.start() : chain_match.end()]
        el_string_match = split_class_attributes.search(_regex_input(el_string))
        assert el_string_match is not None
        tag_part = el_string[el_string_match.start(1) : el_string_match.end(1)]
        attrs_part = el_string[el_string_match.start(3) : el_string_match.end(3)]
        attributes = parse_attributes_regex.finditer(_regex_input(attrs_part))

        element = Element(order=idx)

        if tag_part:
            tag_and_class = tag_part.split(".", 1)
            element.tag_name = tag_and_class[0]
            if len(tag_and_class) > 1:
                element.attr_class = [cl for cl in tag_and_class[1].split(".") if cl != ""]

        for ii in attributes:
            item = {
                name: attrs_part[ii.start(group) : ii.end(group)]
                for name, group in parse_attributes_regex.groupindex.items()
            }
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


def wanted_attribute_entries(wanted_data_attributes: list[str]) -> list[str]:
    return [attribute.strip() for attribute in wanted_data_attributes if attribute.strip()][:_MAX_DATA_ATTRIBUTES]


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
    entries = wanted_attribute_entries(wanted_data_attributes)
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
    for idx, chain_match in enumerate(split_chain_regex.finditer(_regex_input(chain))):
        el_string = chain[chain_match.start() : chain_match.end()]
        el_string_match = split_class_attributes.search(_regex_input(el_string))
        tag_part = el_string[el_string_match.start(1) : el_string_match.end(1)] if el_string_match else ""
        attrs_part = el_string[el_string_match.start(3) : el_string_match.end(3)] if el_string_match else None

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
            for attribute_match in parse_attributes_regex.finditer(_regex_input(attrs_part)):
                key_group = parse_attributes_regex.groupindex["key"]
                value_group = parse_attributes_regex.groupindex["value"]
                key = attrs_part[attribute_match.start(key_group) : attribute_match.end(key_group)]
                value = attrs_part[attribute_match.start(value_group) : attribute_match.end(value_group)]
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
