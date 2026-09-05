"""Frozen copy of the pre-#80653 selector compiler.

Vendored verbatim from master @ 1b114bf0, the #83169 merge that widened the
part tail to `[^;]` and normalized attribute-quote escaping — production
behavior since 2026-08-18, and the baseline "old" counts must reflect:
- `SelectorPart`, `Selector` from posthog/models/event/event.py
- `build_selector_regex` and `_chain_escaped_value` from posthog/models/property/util.py

This copy must keep compiling selectors exactly the way production did before
PR #80653, so the audit can compute "what would the old compiler have matched"
after the in-repo compiler changes. Do not edit the vendored bodies; diff them
against the source commit instead.
"""

import re
import copy
from typing import Optional, Union

SELECTOR_ATTRIBUTE_REGEX = r"([a-zA-Z]*)\[(.*)=[\'|\"](.*)[\'|\"]\]"


class SelectorPart:
    direct_descendant = False
    unique_order = 0

    def __init__(self, tag: str, direct_descendant: bool, escape_slashes: bool):
        self.direct_descendant = direct_descendant
        self.data: dict[str, Union[str, list]] = {}
        self.ch_attributes: dict[str, Union[str, list]] = {}  # attributes for CH

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


def _chain_escaped_value(value: str) -> str:
    # A quoted value in the chain escapes double quotes as \" (_escape in
    # posthog/models/element/element.py). A selector can write the quote either
    # pre-escaped ([title="say \"hi\""]) or bare inside single quotes
    # ([title='say "hi"']), so normalize to the chain's form to match both.
    return value.replace(r"\"", '"').replace('"', r"\"")


def build_selector_regex(selector: Selector) -> str:
    regex = r""
    for tag in selector.parts:
        if tag.data.get("tag_name") and isinstance(tag.data["tag_name"], str) and tag.data["tag_name"] != "*":
            # The elements in the elements_chain are separated by the semicolon
            regex += re.escape(tag.data["tag_name"])
        if tag.data.get("attr_class__contains"):
            regex += r".*?\." + r"\..*?".join([re.escape(s) for s in sorted(tag.data["attr_class__contains"])])
        if tag.ch_attributes:
            regex += r".*?"
            for key, value in sorted(tag.ch_attributes.items()):
                regex += rf'{re.escape(key)}="{re.escape(_chain_escaped_value(str(value)))}".*?'
        # The rest of the element can carry characters an allowlist cannot
        # anticipate (classes like w-1/2 or !mt-0), so skip anything up to the
        # `;` element separator.
        regex += r"[^;]*?($|;|:([^;^\s]*(;|$|\s)))"
        if tag.direct_descendant:
            regex += r".*"
    if regex:
        # Always start matching at the beginning of an element in the chain string
        # This is to avoid issues like matching elements with class "foo" when looking for elements with tag name "foo"
        return r"(^|;)" + regex
    else:
        return r""
