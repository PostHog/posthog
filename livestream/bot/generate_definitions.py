#!/usr/bin/env python3
"""Generate bot definitions JSON for the Go livestream service.

Reads from products/web_analytics/backend/hogql_queries/bot_definitions.py (single source of truth)
and writes livestream/bot/definitions.json.

Run from repo root:
    python livestream/bot/generate_definitions.py

posthog/test/repo_invariants/test_bot_definitions_go_sync.py fails when the committed JSON drifts
from this output, so the generator is the only supported way to change the file.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS  # noqa: E402

output_path = Path(__file__).parent / "definitions.json"

# A substring matcher cannot represent these RE2 constructs: quantifiers, character classes,
# groups, alternation, and anchors all change what matches where.
_REGEX_METACHARACTERS = frozenset("*+?{}[]()|^$")


def to_substring(pattern: str) -> str | None:
    """Return the literal substring the Go classifier should look for, or None to drop the pattern.

    ClickHouse reads BOT_DEFINITIONS keys as RE2 regexes, but the Go livestream classifier matches
    them as Aho-Corasick substrings, where every byte is literal. A pattern that only escapes
    literal characters (`desktop\\.hog\\.dev`) has a substring form and is de-escaped. A pattern
    that relies on a regex feature (`Chrome/1\\d\\d.*`, `Safari/537\\.3$`) has none, so it is
    dropped rather than turned into a substring that can never match. A bare `.` is kept as a
    literal dot, which is what these patterns intend and what the substring engine matches anyway.
    """
    result: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            if index + 1 >= len(pattern):
                return None  # a dangling backslash is not a literal we can reproduce
            following = pattern[index + 1]
            if following.isalnum():
                return None  # \d \s \w \b \1 — a class, anchor, or backreference
            result.append(following)  # \. \) \/ … — the escaped literal character
            index += 2
            continue
        if char in _REGEX_METACHARACTERS:
            return None
        result.append(char)
        index += 1
    return "".join(result)


def build_entries() -> tuple[list[dict[str, str]], list[str]]:
    """Return the (entries, dropped patterns) derived from BOT_DEFINITIONS."""
    entries: list[dict[str, str]] = []
    dropped: list[str] = []
    for pattern, bot_def in BOT_DEFINITIONS.items():
        literal = to_substring(pattern)
        if literal is None:
            dropped.append(pattern)
            continue
        entries.append(
            {
                "pattern": literal,
                "name": bot_def.name,
                "category": bot_def.category,
                "traffic_type": bot_def.traffic_type,
            }
        )
    return entries, dropped


def render() -> str:
    """The exact file contents the generator writes, so a test can compare without writing."""
    entries, _dropped = build_entries()
    return json.dumps(entries, indent=2) + "\n"


def main() -> None:
    entries, dropped = build_entries()
    output_path.write_text(render())
    sys.stdout.write(f"Generated {output_path} with {len(entries)} bot definitions\n")
    if dropped:
        sys.stdout.write(f"Dropped {len(dropped)} regex-only patterns the substring matcher cannot represent:\n")
        for pattern in dropped:
            sys.stdout.write(f"  {pattern}\n")


if __name__ == "__main__":
    main()
