#!/usr/bin/env python3
"""Merge the snapshot blocks of one syrupy amber file into another.

Usage: merge-amber-snapshots.py <existing> <incoming>

A sharded test job writes only the snapshots of the tests it ran, so two shards can both create the
same amber file with different blocks. Their union, sorted by name, is what an unsharded run writes.
The merged file replaces <existing>.
"""

import sys
from pathlib import Path

VERSION_LINE = "# serializer version: 1\n"
NAME_MARKER = "# name: "
DIVIDER = "# ---\n"


def parse_blocks(text: str) -> dict[str, str]:
    if not text.startswith(VERSION_LINE):
        raise SystemExit(f"not a serializer version 1 amber file: {text[:40]!r}")
    blocks: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in text[len(VERSION_LINE) :].splitlines(keepends=True):
        if name is None:
            if not line.startswith(NAME_MARKER):
                raise SystemExit(f"expected a name marker, got {line!r}")
            name = line[len(NAME_MARKER) :].rstrip("\n")
            lines = [line]
            continue
        lines.append(line)
        if line == DIVIDER:
            blocks[name] = "".join(lines)
            name = None
    if name is not None:
        raise SystemExit(f"unterminated block {name!r}")
    return blocks


def main(existing_path: str, incoming_path: str) -> None:
    existing = Path(existing_path)
    merged = parse_blocks(existing.read_text())
    for name, block in parse_blocks(Path(incoming_path).read_text()).items():
        if name in merged and merged[name] != block:
            sys.stderr.write(
                f"::warning::{existing_path}: snapshot {name!r} differs between shards; keeping the first\n"
            )
            continue
        merged[name] = block
    existing.write_text(VERSION_LINE + "".join(merged[name] for name in sorted(merged)))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
