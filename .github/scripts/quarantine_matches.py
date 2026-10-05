"""Report which quarantine file entry covers each test of the weekly flaky report.

Usage: ``quarantine_matches.py <quarantine-file> <runner> <covering-since>``

stdin is ``{"<test>": ["<name the test can carry>", ...]}``, most complete name first.
stdout is ``{"<test>": {"id": ..., "expires": ...}}`` for the covered tests only.
A file that is missing or breaks the contract exits 1, so the caller cannot read it as "no entry".
"""

from __future__ import annotations

import sys
import json
from datetime import date
from pathlib import Path

from hogli_commands.quarantine import core


def main(argv: list[str]) -> str | None:
    path, runner, covering_since = Path(argv[1]), argv[2], date.fromisoformat(argv[3])
    if not path.is_file():
        return f"{path} is missing"
    loaded = core.load(path)
    if loaded.errors:
        return "; ".join(loaded.errors)
    # An entry that expired on or after `covering_since` suppressed runs the report counts.
    entries = core.active_entries(loaded.entries, runner, covering_since)
    names_by_test: dict[str, list[str]] = json.load(sys.stdin)
    covered: dict[str, dict[str, str]] = {}
    for test, names in names_by_test.items():
        entry = next((match for match in (core.find_match(entries, name) for name in names) if match), None)
        if entry is not None:
            covered[test] = {"id": entry.id, "expires": entry.expires.isoformat()}
    json.dump(covered, sys.stdout)
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv))
