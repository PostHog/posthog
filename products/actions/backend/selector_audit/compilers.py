"""Old-vs-new selector compilation for the action selector audit.

Wraps the vendored compiler copies (`_old_compiler` from master pre-#80653,
`_new_compiler` from the PR branch) behind selector-string functions, mirroring
how query-time matching calls them: `Selector(s, escape_slashes=False)` as in
`selector_to_expr` (posthog/hogql/property.py). This module stays importable
without Django so the compilers can be exercised standalone.
"""

import re

from posthog.dataclasses import frozen

from . import _new_compiler, _old_compiler

# The tail character class the old compiler used before #83169 widened it to
# [^;]. Selectors with characters outside this set matched zero events until
# that fix deployed (2026-08-18), so their "old" baseline jumped mid-history;
# the flag marks them so owners can read counts spanning that deploy correctly.
OLD_TAIL_ALLOWED_CHARS = frozenset('-_.:"= [](),abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')

STRUCTURE_SINGLE_SIMPLE = "single_simple"
STRUCTURE_MULTI_CONDITION = "multi_condition"
STRUCTURE_MULTI_PART = "multi_part"
STRUCTURE_MULTI_PART_DIRECT = "multi_part_direct"
STRUCTURE_EMPTY = "empty"


def compile_old(selector: str) -> str:
    """The elements_chain regex production compiled this selector to before PR #80653."""
    return _old_compiler.build_selector_regex(_old_compiler.Selector(selector, escape_slashes=False))


def compile_new(selector: str) -> str:
    """The elements_chain regex PR #80653 compiles this selector to."""
    return _new_compiler.build_selector_regex(_new_compiler.Selector(selector, escape_slashes=False))


def rewrite_direct_descendants(selector: str) -> str:
    """The selector with every `>` combinator replaced by a descendant space.

    Returns the input unchanged (including spacing) when it has no `>` token, so
    `rewrite != selector` reliably means "a rewrite exists".
    """
    # Both compilers blindly erase these star hops before parsing (see
    # Selector.__init__), so split the same normalized string. Splitting the raw
    # string keeps the star as a real part, and `div * button` demands an
    # intermediate element the compiled original never required.
    normalized = selector.replace("> * > ", "").replace("> *", "")
    tokens = [token for token in _split_selector(normalized) if token != ""]
    if ">" not in tokens:
        return selector
    return " ".join(token for token in tokens if token != ">")


# Both compilers split combinator tokens identically; either vendored copy works.
_SPLITTER = _new_compiler.Selector("")


def _split_selector(selector: str) -> list[str]:
    return list(_SPLITTER._split(selector.strip()))


@frozen
class SelectorClassification:
    structure: str
    part_count: int
    has_direct_descendant: bool
    has_nth_child: bool
    outside_old_allowlist: bool
    unsupported_css: bool


def classify_selector(selector: str) -> SelectorClassification:
    """Structural classification, parsed with the new (CSS-faithful) parser."""
    parsed = _new_compiler.Selector(selector, escape_slashes=False)
    condition_values: list[str] = []
    has_nth = False
    for part in parsed.parts:
        for key, value in part.data.items():
            if key in ("nth_child", "nth_of_type"):
                has_nth = True
            if isinstance(value, list):
                condition_values.extend(str(item) for item in value)
            else:
                condition_values.append(str(value))
        condition_values.extend(str(key) for key in part.ch_attributes)

    if not parsed.parts:
        structure = STRUCTURE_EMPTY
    elif len(parsed.parts) == 1:
        structure = STRUCTURE_SINGLE_SIMPLE if len(parsed.parts[0].data) <= 1 else STRUCTURE_MULTI_CONDITION
    elif any(part.direct_descendant for part in parsed.parts):
        structure = STRUCTURE_MULTI_PART_DIRECT
    else:
        structure = STRUCTURE_MULTI_PART

    outside_allowlist = any(char not in OLD_TAIL_ALLOWED_CHARS for value in condition_values for char in value)
    return SelectorClassification(
        structure=structure,
        part_count=len(parsed.parts),
        has_direct_descendant=any(part.direct_descendant for part in parsed.parts),
        has_nth_child=has_nth,
        outside_old_allowlist=outside_allowlist,
        unsupported_css=parsed.has_unsupported_syntax(),
    )


def is_valid_regex(pattern: str) -> bool:
    """Guards the ClickHouse batch: one invalid pattern fails the whole countIf query."""
    if pattern == "":
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True
