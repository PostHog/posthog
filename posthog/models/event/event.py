import copy
import datetime
import re
from collections import defaultdict
from typing import Dict, List, Optional, Union

from dateutil.relativedelta import relativedelta
from django.db import models
from django.utils import timezone

from posthog.models.team import Team

SELECTOR_ATTRIBUTE_REGEX = r"([a-zA-Z]*)\[(.*)=[\'|\"](.*)[\'|\"]\]"


LAST_UPDATED_TEAM_ACTION: Dict[int, datetime.datetime] = {}
TEAM_EVENT_ACTION_QUERY_CACHE: Dict[int, Dict[str, tuple]] = defaultdict(dict)
# TEAM_EVENT_ACTION_QUERY_CACHE looks like team_id -> event ex('$pageview') -> query
TEAM_ACTION_QUERY_CACHE: Dict[int, str] = {}
DEFAULT_EARLIEST_TIME_DELTA = relativedelta(weeks=1)


class SelectorPart:
    direct_descendant = False
    unique_order = 0

    def __init__(self, tag: str, direct_descendant: bool, escape_slashes: bool):
        self.direct_descendant = direct_descendant
        self.data: Dict[str, Union[str, List]] = {}
        self.ch_attributes: Dict[str, Union[str, List]] = {}  # attributes for CH

        result = re.search(SELECTOR_ATTRIBUTE_REGEX, tag)
        if result and "[id=" in tag:
            self.data["attr_id"] = result[3]
            self.ch_attributes["attr_id"] = result[3]
            tag = result[1]
        if result and "[" in tag:
            self.data[f"attributes__attr__{result[2]}"] = result[3]
            self.ch_attributes[result[2]] = result[3]
            tag = result[1]
        if "nth-child(" in tag:
            parts = tag.split(":nth-child(")
            self.data["nth_child"] = parts[1].replace(")", "")
            self.ch_attributes["nth-child"] = self.data["nth_child"]
            tag = parts[0]
        if "." in tag:
            parts = tag.split(".")
            # Strip all slashes that are not followed by another slash
            self.data["attr_class__contains"] = [self._unescape_class(p) if escape_slashes else p for p in parts[1:]]
            tag = parts[0]
        if tag:
            self.data["tag_name"] = tag

    @property
    def extra_query(self) -> Dict[str, List[Union[str, List[str]]]]:
        where: List[Union[str, List[str]]] = []
        params: List[Union[str, List[str]]] = []
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
    parts: List[SelectorPart] = []

    def __init__(self, selector: str, escape_slashes=True):
        self.parts = []
        # Sometimes people manually add *, just remove them as they don't do anything
        selector = selector.replace("> * > ", "").replace("> *", "").strip()
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
        part: List[str] = []
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

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200)
    properties: models.JSONField = models.JSONField(default=dict)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    elements_hash: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    site_url: models.CharField = models.CharField(max_length=200, null=True, blank=True)

    # DEPRECATED: elements are stored against element groups now
    elements: models.JSONField = models.JSONField(default=list, null=True, blank=True)
