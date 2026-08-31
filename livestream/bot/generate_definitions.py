#!/usr/bin/env python3
"""Generate bot definitions JSON for the Go livestream service.

Reads from products/web_analytics/backend/hogql_queries/bot_definitions.py (single source of truth)
and writes livestream/bot/definitions.json.

Run from repo root:
    python livestream/bot/generate_definitions.py
"""

from __future__ import annotations

import re
import sys
import json
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS  # noqa: E402

# ClickHouse evaluates the patterns as regexes, but the Go classifier matches them as
# Aho-Corasick substrings, where a backslash is just another character to look for. So a
# pattern like `bne\.es_bot` would never match the user agent it was written for.
_REGEX_ESCAPE = re.compile(r"\\(.)")


def as_literal(pattern: str) -> str:
    return _REGEX_ESCAPE.sub(r"\1", pattern)


entries = [
    {
        "pattern": as_literal(pattern),
        "name": bot_def.name,
        "category": bot_def.category,
        "traffic_type": bot_def.traffic_type,
    }
    for pattern, bot_def in BOT_DEFINITIONS.items()
]

output_path = Path(__file__).parent / "definitions.json"
output_path.write_text(json.dumps(entries, indent=2) + "\n")
sys.stdout.write(f"Generated {output_path} with {len(entries)} bot definitions\n")
