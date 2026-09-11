import copy
import datetime
from collections import defaultdict
from typing import Optional, Union

from django.db import models
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from posthog.models.team import Team

SELECTOR_ATTRIBUTE_REGEX = r"([a-zA-Z]*)\[(.*)=[\'|\"](.*)[\'|\"]\]"


def _selector_attribute(tag: str) -> tuple[str, str, str] | None:
    # Preserve the legacy pattern's greedy captures and first matching line,
    # including its acceptance of | as a quote, without retrying every opener.
    for line in tag.split("\n"):
        end = max(line.rfind(quote + "]") for quote in "'\"|")
        if end < 0:
            continue
        separator = max(line.rfind("=" + quote, 0, end) for quote in "'\"|")
        if separator < 0:
            continue
        opening = line.find("[", 0, separator)
        if opening < 0:
            continue
        start = opening
        while start > 0 and ("a" <= line[start - 1] <= "z" or "A" <= line[start - 1] <= "Z"):
            start -= 1
        return line[start:opening], line[opening + 1 : separator], line[separator + 2 : end]
    return None


def _split_selector_classes(tag: str) -> list[str]:
    # A dot is excluded when a ] follows it before the next [. Scan once from
    # the right to preserve that rule even for malformed/unbalanced brackets.
    boundaries = []
    closing_bracket = False
    for index in range(len(tag) - 1, -1, -1):
        if tag[index] == "]":
            closing_bracket = True
        elif tag[index] == "[":
            closing_bracket = False
        elif tag[index] == "." and not closing_bracket:
            boundaries.append(index)
    parts = []
    start = 0
    for index in reversed(boundaries):
        parts.append(tag[start:index])
        start = index + 1
    parts.append(tag[start:])
    return parts


LAST_UPDATED_TEAM_ACTION: dict[int, datetime.datetime] = {}
TEAM_EVENT_ACTION_QUERY_CACHE: dict[int, dict[str, tuple]] = defaultdict(dict)
# TEAM_EVENT_ACTION_QUERY_CACHE looks like team_id -> event ex('$pageview') -> query
TEAM_ACTION_QUERY_CACHE: dict[int, str] = {}
DEFAULT_EARLIEST_TIME_DELTA = relativedelta(weeks=1)


class SelectorPart:
    direct_descendant = False
    unique_order = 0

    def __init__(self, tag: str, direct_descendant: bool, escape_slashes: bool):
        self.direct_descendant = direct_descendant
        self.data: dict[str, Union[str, list]] = {}
        self.ch_attributes: dict[str, Union[str, list]] = {}  # attributes for CH

        result = _selector_attribute(tag)
        if result and "[id=" in tag:
            self.data["attr_id"] = result[2]
            self.ch_attributes["attr_id"] = result[2]
            tag = result[0]
        if result and "[" in tag:
            self.data[f"attributes__attr__{result[1]}"] = result[2]
            self.ch_attributes[result[1]] = result[2]
            tag = result[0]
        if ":nth-child(" in tag:
            parts = tag.split(":nth-child(")
            self.data["nth_child"] = parts[1].replace(")", "")
            self.ch_attributes["nth-child"] = self.data["nth_child"]
            tag = parts[0]
        if "." in tag:
            parts = _split_selector_classes(tag)
            # Strip all slashes that are not followed by another slash
            self.data["attr_class__contains"] = [self._unescape_class(p) if escape_slashes else p for p in parts[1:]]
            tag = parts[0]
        if "#" in tag:
            parts = tag.split("#")
            if len(parts) > 1:
                self.data["attr_id"] = self._unescape_class(parts[1]) if escape_slashes else parts[1]
                self.ch_attributes["attr_id"] = self.data["attr_id"]
            tag = parts[0]
        if tag:
            self.data["tag_name"] = tag

    @property
    def extra_query(self) -> dict[str, list[Union[str, list[str]]]]:
        where: list[Union[str, list[str]]] = []
        params: list[Union[str, list[str]]] = []
        for key, value in self.data.items():
            if "attr__" in key:
                where.append(f"(attributes ->> 'attr__{key.split('attr__')[1]}') = %s")
            else:
                if "__contains" in key:
                    where.append(f"{key.replace('__contains', '')} @> %s::varchar(200)[]")
                else:
                    where.append(f"{key} = %s")
            params.append(value)
        return {"where": where, "params": params}

    def _unescape_class(self, class_name):
        r"""Separate all double slashes "\\" (replace them with "\") and remove all single slashes between them."""
        return "\\".join([p.replace("\\", "") for p in class_name.split("\\\\")])


class Selector:
    parts: list[SelectorPart] = []

    def __init__(self, selector: str, escape_slashes=True):
        self.parts = []
        # Sometimes people manually add *, just remove them as they don't do anything
        selector = selector.replace("> * > ", "").replace("> *", "").replace("\\:", ":").strip()
        tags = list(self._split(selector))
        tags.reverse()
        # Detecting selector parts
        for index, tag in enumerate(tags):
            if tag == ">" or tag == "":
                continue
            direct_descendant = index > 0 and tags[index - 1] == ">"
            part = SelectorPart(tag, direct_descendant, escape_slashes)
            part.unique_order = len([p for p in self.parts if p.data == part.data])
            self.parts.append(copy.deepcopy(part))

    def _split(self, selector):
        in_attribute_selector = False
        in_quotes: Optional[str] = None
        part: list[str] = []
        for char in selector:
            if char == "[" and in_quotes is None:
                in_attribute_selector = True
            if char == "]" and in_quotes is None:
                in_attribute_selector = False
            if char in "\"'":
                if in_quotes is not None:
                    if in_quotes == char:
                        in_quotes = None
                else:
                    in_quotes = char

            if char == " " and not in_attribute_selector:
                yield "".join(part)
                part = []
            else:
                part.append(char)

        yield "".join(part)


class Event(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    event = models.CharField(max_length=200, null=True, blank=True)
    distinct_id = models.CharField(max_length=200)
    properties = models.JSONField(default=dict)
    timestamp = models.DateTimeField(default=timezone.now, blank=True)
    elements_hash = models.CharField(max_length=200, null=True, blank=True)
    site_url = models.CharField(max_length=200, null=True, blank=True)

    # DEPRECATED: elements are stored against element groups now
    elements = models.JSONField(default=list, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["elements_hash"]),
            models.Index(fields=["timestamp", "team_id", "event"]),
            # Separately managed:
            # models.Index(fields=["created_at"]),
            # NOTE: The below index has been added as a manual migration in
            # `posthog/migrations/0024_add_event_distinct_id_index.py, but I'm
            # adding this here to improve visibility.
            # models.Index(fields=["distinct_id"], name="idx_distinct_id"),
        ]
