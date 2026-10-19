import re
from collections.abc import Callable, Iterator

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.dataclasses import frozen


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


# Below splits the tag/classes from attributes
# Needs a regex because classes can have : too
split_class_attributes = re.compile(r"(.*?)($|:([a-zA-Z\-\_0-9]*=.*))")

_CHAIN_SEPARATOR = ";"
_QUOTE = '"'
_ESCAPE = "\\"


@frozen
class ElementAttribute:
    key: str
    value: str


def _find_closing_quote(chain: str, opening: int) -> int:
    """Returns the index of the quote that closes the value opened at `opening`, or -1.

    A backslash escapes the character after it, so an escaped quote never closes the value.
    """
    position = opening + 1
    length = len(chain)
    while position < length:
        char = chain[position]
        if char == _ESCAPE:
            position += 2
        elif char == _QUOTE:
            return position
        else:
            position += 1
    return -1


def split_elements_chain(chain: str) -> list[str]:
    """Splits an elements chain into one string per element.

    Elements are separated by whitespace or semicolons outside quoted attribute values.
    Inside a quoted value both are literal and a backslash escapes the next character.
    A quote with no closing quote ends the current element and is dropped. The chain is
    client-supplied, so this is a single left-to-right pass: every character is visited
    once, and no input shape can make it backtrack.
    """
    elements: list[str] = []
    token_start = -1
    position = 0
    length = len(chain)
    # A failed search for a closing quote skipped every later quote as escaped, so the
    # same search from any later quote fails too and must not scan the chain again.
    closing_quotes_remain = True

    def end_token(end: int) -> None:
        nonlocal token_start
        if token_start != -1 and end > token_start:
            elements.append(chain[token_start:end])
        token_start = -1

    while position < length:
        char = chain[position]
        if char == _QUOTE:
            closing = _find_closing_quote(chain, position) if closing_quotes_remain else -1
            if closing == -1:
                closing_quotes_remain = False
                end_token(position)
                position += 1
                continue
            if token_start == -1:
                token_start = position
            position = closing + 1
        elif char == _CHAIN_SEPARATOR or char.isspace():
            end_token(position)
            position += 1
        else:
            if token_start == -1:
                token_start = position
            position += 1
    end_token(length)
    return elements


def _find_attribute_value_end(attrs: str, value_start: int) -> int:
    """Returns the index of the quote that closes the value starting at `value_start`, or -1.

    The closing quote must follow a character that is not a backslash. The value cannot
    contain a newline, except as that final character before the quote.
    """
    position = value_start
    last = len(attrs) - 1
    while position < last:
        char = attrs[position]
        if char != _ESCAPE and attrs[position + 1] == _QUOTE:
            return position + 1
        if char == "\n":
            return -1
        position += 1
    return -1


def iter_element_attributes(attrs: str) -> Iterator[ElementAttribute]:
    """Yields the attributes found in the attributes part of one element string.

    Each attribute is key="value". The key runs from the end of the previous attribute
    to the next =" on the same line. If no closing quote follows on that line, nothing
    before the end of the line can start an attribute, so scanning resumes after it.
    This keeps the scan to a single pass over client-supplied input.
    """
    start = 0
    while True:
        separator = attrs.find('="', start)
        if separator == -1:
            return
        newline = attrs.find("\n", start, separator)
        if newline != -1:
            start = newline + 1
            continue
        value_start = separator + 2
        closing = _find_attribute_value_end(attrs, value_start)
        if closing == -1:
            newline = attrs.find("\n", value_start)
            if newline == -1:
                return
            start = newline + 1
            continue
        yield ElementAttribute(key=attrs[start:separator], value=attrs[value_start:closing])
        start = closing + 1


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


_PROMOTED_ATTRIBUTES: dict[str, tuple[str, Callable[[str], object]]] = {
    "text": ("text", str),
    "href": ("href", str),
    "attr_id": ("attr_id", str),
    "nth-child": ("nth_child", int),
    "nth-of-type": ("nth_of_type", int),
}


def _parse_element(el_string: str, order: int, attributes_filter: Callable[[str], bool] | None) -> dict:
    match = split_class_attributes.search(el_string)
    tag_part = match.group(1) if match else ""
    attrs_part = match.group(3) if match else None

    element: dict = {
        "text": None,
        "tag_name": None,
        "attr_class": None,
        "href": None,
        "attr_id": None,
        "nth_child": None,
        "nth_of_type": None,
        "attributes": {},
        "order": order,
    }

    if tag_part:
        tag_and_class = tag_part.split(".", 1)
        element["tag_name"] = tag_and_class[0]
        if len(tag_and_class) > 1:
            element["attr_class"] = [cl for cl in tag_and_class[1].split(".") if cl != ""]

    if attrs_part:
        for attribute in iter_element_attributes(attrs_part):
            promoted = _PROMOTED_ATTRIBUTES.get(attribute.key)
            if promoted:
                field, convert = promoted
                element[field] = convert(attribute.value)
            elif attribute.key and (attributes_filter is None or attributes_filter(attribute.key)):
                element["attributes"][attribute.key] = attribute.value

    return element


def chain_to_element_dicts(chain: str, attributes_filter: Callable[[str], bool] | None = None) -> list[dict]:
    """
    Converts an elements chain string into serialized element dicts, shaped exactly like
    ElementSerializer output but without instantiating Element models, so the elements API
    can serialize large pages cheaply. attributes_filter optionally restricts the attributes
    map to matching keys (see build_attributes_filter).
    """
    return [
        _parse_element(el_string, idx, attributes_filter) for idx, el_string in enumerate(split_elements_chain(chain))
    ]


def chain_to_elements(chain: str) -> list[Element]:
    """
    Converts an elements chain string into a list of Element objects.
    """
    return [Element(**element) for element in chain_to_element_dicts(chain)]
