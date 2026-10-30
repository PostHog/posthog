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


_QUOTE = '"'
_ESCAPE = "\\"
_NEWLINE = "\n"
_ATTRIBUTE_SEPARATOR = ":"
# The chain is client-supplied, so every scan below must stay linear in its length. These
# patterns are a single character class or a class run before one literal, which cannot
# backtrack, and the scanners move past each match so no character is searched twice.
_BARE_RUN_END = re.compile(r'[\s;"]')
_ATTRIBUTE_KEY = re.compile(r"[a-zA-Z0-9_-]*=")


@frozen
class ElementAttribute:
    key: str
    value: str


def _find_closing_quote(text: str, value_start: int) -> int:
    """Returns the index of the quote that closes the value starting at `value_start`, or -1.

    Serializers escape a quote inside a value with a backslash and escape nothing else, so
    a quote preceded by a backslash never closes the value. The value may be empty.
    """
    position = value_start
    while True:
        closing = text.find(_QUOTE, position)
        if closing == -1:
            return -1
        if text[closing - 1] != _ESCAPE:
            return closing
        position = closing + 1


def split_elements_chain(chain: str) -> list[str]:
    """Splits an elements chain into one string per element.

    Elements are separated by whitespace or semicolons outside quoted attribute values.
    Inside a quoted value both are literal and a quote preceded by a backslash is escaped.
    A quote with no closing quote ends the current element and is dropped, unless the
    chain ends with an escaped quote, which then closes the value. This is a
    single left-to-right pass over client-supplied input: no input shape can make it
    scan a character twice.
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
        boundary = _BARE_RUN_END.search(chain, position)
        if boundary is None:
            if token_start == -1:
                token_start = position
            break
        boundary_start = boundary.start()
        if boundary_start > position and token_start == -1:
            token_start = position
        if boundary.group() == _QUOTE:
            closing = _find_closing_quote(chain, boundary_start + 1) if closing_quotes_remain else -1
            if closing == -1 and length - 1 > boundary_start and chain.endswith(_ESCAPE + _QUOTE):
                # Serializers escape quotes but not backslashes, so a value that ends in a
                # backslash at the end of the chain reads as unterminated. It closes there.
                closing = length - 1
            if closing == -1:
                closing_quotes_remain = False
                end_token(boundary_start)
                position = boundary_start + 1
                continue
            if token_start == -1:
                token_start = boundary_start
            position = closing + 1
        else:
            end_token(boundary_start)
            position = boundary_start + 1
    end_token(length)
    return elements


@frozen
class _ElementParts:
    tag: str
    attributes: str | None


def _split_tag_and_attributes(el_string: str) -> _ElementParts:
    """Splits one element string into its tag part and its attributes part.

    The attributes start at the first colon followed by a key and an equals sign, so a
    class name may contain a colon. A line that holds no such colon is skipped unless it
    is the last line, which then forms the tag part on its own. Each colon only scans the
    key characters after it, which the next colon cannot share, so the scan stays linear.
    """
    line_start = 0
    length = len(el_string)
    while True:
        line_end = el_string.find(_NEWLINE, line_start)
        if line_end == -1:
            line_end = length
        colon = el_string.find(_ATTRIBUTE_SEPARATOR, line_start, line_end)
        while colon != -1:
            if _ATTRIBUTE_KEY.match(el_string, colon + 1, line_end) is not None:
                return _ElementParts(tag=el_string[line_start:colon], attributes=el_string[colon + 1 : line_end])
            colon = el_string.find(_ATTRIBUTE_SEPARATOR, colon + 1, line_end)
        if line_end >= length - 1:
            return _ElementParts(tag=el_string[line_start:line_end], attributes=None)
        line_start = line_end + 1


def iter_element_attributes(attrs: str) -> Iterator[ElementAttribute]:
    """Yields the attributes found in the attributes part of one element string.

    Each attribute is key="value". The key runs from the end of the previous attribute to
    the next =". A failed search for a closing quote skipped every later quote as escaped,
    so the same search from any later =" fails too and the scan ends. This keeps the scan
    to a single pass over client-supplied input.
    """
    start = 0
    while True:
        separator = attrs.find('="', start)
        if separator == -1:
            return
        value_start = separator + 2
        closing = _find_closing_quote(attrs, value_start)
        if closing == -1:
            return
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


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


_PROMOTED_ATTRIBUTES: dict[str, tuple[str, Callable[[str], object]]] = {
    "text": ("text", str),
    "href": ("href", str),
    "attr_id": ("attr_id", str),
    "nth-child": ("nth_child", _int_or_none),
    "nth-of-type": ("nth_of_type", _int_or_none),
}


def _parse_element(el_string: str, order: int, attributes_filter: Callable[[str], bool] | None) -> dict:
    parts = _split_tag_and_attributes(el_string)
    tag_part = parts.tag
    attrs_part = parts.attributes

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
