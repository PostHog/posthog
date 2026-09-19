"""Frozen copy of the PR #80653 selector compiler.

Vendored verbatim from the PR branch @ c7ac3070 (includes eb7be9ef):
- `SelectorPart`, `Selector` and parser constants from posthog/models/event/event.py
- `build_selector_regex` and its helpers from posthog/models/property/util.py

This copy lets the audit compute "what will the new compiler match" before the
PR merges, and keeps old-vs-new comparisons stable afterwards. Do not edit the
vendored bodies; diff them against the source commit instead.
"""

import re
import copy
from typing import Optional, Union

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


# Attribute keys the elements chain serializes without the attr__ prefix that custom
# HTML attributes get. See elements_to_string in posthog/models/element/element.py.
_UNPREFIXED_CHAIN_ATTRIBUTES = {"attr_id", "href", "text", "nth-child", "nth-of-type"}


def _chain_attribute_order(key: str) -> str:
    """The key this attribute sorts under in the elements chain.

    elements_to_string sorts by serialized key, so a custom attribute sorts under
    attr__<key>. Emit attributes in that order: the separators between them cannot
    match backwards, so an order the chain never produces can never match.
    """
    return key if key in _UNPREFIXED_CHAIN_ATTRIBUTES else f"attr__{key}"


# A semicolon separates elements only outside a quoted attribute value — an inline
# style="display: flex; gap: 4px" carries its own. Quotes inside a value are escaped
# as \" (see _escape in posthog/models/element/element.py), so an escaped quote must
# not close the span. split_chain_regex draws the boundary the same way.
_QUOTED_VALUE = r'"(?:\\.|[^"])*"'
_WITHIN_ELEMENT = r'(?:[^;"]|' + _QUOTED_VALUE + r")*?"
_WHOLE_ELEMENTS = r'(?:(?:[^;"]|' + _QUOTED_VALUE + r")*;)*"


def build_selector_regex(selector: Selector) -> str:
    regex = r""
    for index, tag in enumerate(selector.parts):
        if index > 0 and not tag.direct_descendant:
            # A descendant combinator (a space) matches through any number of
            # intermediate elements. Skip whole elements only — an unanchored .*
            # would let this part match inside a class name or attribute value.
            regex += _WHOLE_ELEMENTS
        if tag.data.get("tag_name") and isinstance(tag.data["tag_name"], str) and tag.data["tag_name"] != "*":
            # The elements in the elements_chain are separated by the semicolon
            regex += re.escape(tag.data["tag_name"])
        if tag.data.get("attr_class__contains"):
            # Every condition of one selector part has to land inside one element
            regex += (
                _WITHIN_ELEMENT
                + r"\."
                + (r"\." + _WITHIN_ELEMENT).join([re.escape(s) for s in sorted(tag.data["attr_class__contains"])])
            )
        if tag.ch_attributes:
            regex += _WITHIN_ELEMENT
            for key, value in sorted(tag.ch_attributes.items(), key=lambda kv: _chain_attribute_order(kv[0])):
                regex += rf'{re.escape(key)}="{re.escape(str(value))}"' + _WITHIN_ELEMENT
        # The rest of the element can carry characters no allowlist anticipates
        # (classes like w-1/2 or !mt-0), so skip anything within the element.
        regex += _WITHIN_ELEMENT + r"($|;|:([^;^\s]*(;|$|\s)))"
        if tag.direct_descendant:
            regex += r".*"
    if regex:
        # Always start matching at the beginning of an element in the chain string
        # This is to avoid issues like matching elements with class "foo" when looking for elements with tag name "foo"
        return r"(^|;)" + regex
    else:
        return r""
