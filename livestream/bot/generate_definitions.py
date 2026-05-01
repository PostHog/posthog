#!/usr/bin/env python3
"""Generate bot definitions JSON for the Go livestream service.

Reads from posthog/hogql_queries/web_analytics/bot_definitions.py (single source of truth)
and writes livestream/bot/definitions.json.

Run from repo root:
    python livestream/bot/generate_definitions.py
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from posthog.hogql_queries.web_analytics.bot_definitions import BOT_DEFINITIONS  # noqa: E402

entries = [
    {
        "pattern": pattern,
        "name": bot_def.name,
        "category": bot_def.category,
        "traffic_type": bot_def.traffic_type,
    }
    for pattern, bot_def in BOT_DEFINITIONS.items()
]

output_path = Path(__file__).parent / "definitions.json"
output_path.write_text(json.dumps(entries, indent=2) + "\n")
sys.stdout.write(f"Generated {output_path} with {len(entries)} bot definitions\n")
