import re
import copy
import datetime
from collections import defaultdict
from typing import Optional, Union

from django.db import models
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from posthog.models.team import Team

SELECTOR_ATTRIBUTE_REGEX = r"\[\s*([^\]\s=]+)\s*=\s*(['\"])(.*?)\2\s*\]"
# The chain records an element's position as nth-child and nth-of-type, and a selector
# can carry either or both. Matching each one lets a selector keep the rest of itself.
POSITIONAL_PSEUDO_CLASS_REGEX = r":(nth-child|nth-of-type)\((\d+)\)"
# A real element tag in the chain is alphanumeric. Anything else left in a parsed
# tag name is unsupported CSS the parser could not peel off.
VALID_TAG_NAME_REGEX = re.compile(r"[a-zA-Z][a-zA-Z0-9-]*")
# An attribute operator (^=, *=, $=, ~=, |=) ends up inside the parsed key, and no
# element chain contains an attribute named that.
VALID_ATTRIBUTE_KEY_REGEX = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:.-]*")
# A pseudo-class written after a class is folded into the class name, and no element
# carries a class called that. A Tailwind variant puts the same word first instead
# (hover:bg-blue), so only the segment after the last colon can be a pseudo-class.
UNSUPPORTED_PSEUDO_CLASSES = frozenset(
    {
        "active",
        "after",
        "before",
        "checked",
        "disabled",
        "empty",
        "enabled",
        "first-child",
        "first-of-type",
        "focus",
        "focus-visible",
        "focus-within",
        "hover",
        "invalid",
        "last-child",
        "last-of-type",
        "only-child",
        "optional",
        "required",
        "root",
        "target",
        "valid",
        "visited",
    }
)


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

        attribute_matches = list(re.finditer(SELECTOR_ATTRIBUTE_REGEX, tag))
        if attribute_matches:
            for match in attribute_matches:
                key = match.group(1)
                value = match.group(3)
                if key == "id":
                    self.data["attr_id"] = value
                    self.ch_attributes["attr_id"] = value
                else:
                    self.data[f"attributes__attr__{key}"] = value
                    self.ch_attributes[key] = value
            # Excise the attribute spans and keep the rest, so a class, id or
            # nth-child written after an attribute selector is not discarded.
            for match in reversed(attribute_matches):
                tag = tag[: match.start()] + tag[match.end() :]
        positional_matches = list(re.finditer(POSITIONAL_PSEUDO_CLASS_REGEX, tag))
        for match in positional_matches:
            pseudo_class, position = match.group(1), match.group(2)
            self.data["nth_child" if pseudo_class == "nth-child" else "nth_of_type"] = position
            self.ch_attributes[pseudo_class] = position
        for match in reversed(positional_matches):
            tag = tag[: match.start()] + tag[match.end() :]
        if "." in tag:
            # Regex pattern that matches dots that are NOT inside square brackets
            # Uses negative lookahead to ensure the dot is not followed by content ending with ]
            # without an opening [ in between
            # Handles Tailwind arbitrary values with square brackets properly.
            # Example: 'div.shadow-[0_4px_6px_rgba(0,0,0,0.1)].text-blue-500'
            # Returns: ['div', 'shadow-[0_4px_6px_rgba(0,0,0,0.1)]', 'text-blue-500']
            pattern = r"\.(?![^\[]*\])"
            parts = re.split(pattern, tag)
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

    def has_unsupported_syntax(self) -> bool:
        # A part keeps unsupported CSS (a pseudo-class, an unsupported combinator, ...)
        # as its tag name, so the compiled regex looks for a tag no real element has and
        # matches nothing.
        for part in self.parts:
            tag = part.data.get("tag_name")
            # "*" is the universal selector, which build_selector_regex supports by
            # skipping the tag name entirely.
            if isinstance(tag, str) and tag != "*" and not VALID_TAG_NAME_REGEX.fullmatch(tag):
                return True
            if any(not VALID_ATTRIBUTE_KEY_REGEX.fullmatch(key) for key in part.ch_attributes):
                return True
            classes = part.data.get("attr_class__contains")
            if isinstance(classes, list) and any(self._class_carries_pseudo_class(name) for name in classes):
                return True
        return False

    @staticmethod
    def _class_carries_pseudo_class(class_name: str) -> bool:
        # Without a colon the whole name is the class, and plenty of real classes share a
        # word with a pseudo-class ("active", "disabled"), so only look past a colon.
        if ":" not in class_name:
            return False
        return class_name.rsplit(":", 1)[-1] in UNSUPPORTED_PSEUDO_CLASSES


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
