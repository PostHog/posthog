#!/usr/bin/env python3
"""Map a module's top-level symbols to line ranges, and emit a layout skeleton to edit.

    uv run --no-project python map_symbols.py products/foo/backend/logic.py
    uv run --no-project python map_symbols.py products/foo/backend/logic.py --skeleton > layout.json

The skeleton puts every symbol in one bucket. Move the entries into modules named
after concerns, then feed it to split_module.py. Editing a generated skeleton beats
retyping 100 symbol names by hand — a typo there becomes a lost function.
"""

from __future__ import annotations

import ast
import json
import argparse
from pathlib import Path


def names_of(node: ast.stmt) -> list[str]:
    """Top-level names a statement binds. Empty for imports, docstrings, and `if TYPE_CHECKING`."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def segment(source: str) -> tuple[dict[str, tuple[int, int]], int]:
    """Symbol -> (first_line, last_line), plus the last line of the leading import block.

    A segment absorbs the comment block directly above the definition, so section
    comments and explanatory notes travel with the code they describe.
    """
    lines = source.splitlines()
    segments: dict[str, tuple[int, int]] = {}
    header_end = 0
    prev_end = 0
    for node in ast.parse(source).body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        j = start - 2
        while j > prev_end - 1 and (lines[j].lstrip().startswith("#") or lines[j].strip() == ""):
            j -= 1
        found = names_of(node)
        for name in found:
            segments[name] = (j + 2, node.end_lineno or start)
        if not found:
            header_end = node.end_lineno or start
        prev_end = node.end_lineno or start
    return segments, header_end


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--skeleton", action="store_true", help="emit a layout JSON skeleton instead of a table")
    args = parser.parse_args()

    source = args.source.read_text()
    segments, header_end = segment(source)

    if args.skeleton:
        ordered = sorted(segments, key=lambda n: segments[n][0])
        print(json.dumps({"UNASSIGNED": {"doc": "TODO one line per module", "symbols": ordered}}, indent=2))
        return 0

    print(f"header (imports, shared state): lines 1-{header_end}")
    print(f"{'lines':>12} {'len':>6}  symbol")
    for name in sorted(segments, key=lambda n: segments[n][0]):
        start, end = segments[name]
        print(f"{start:>5}-{end:<6} {end - start + 1:>6}  {name}")
    print(f"\n{len(segments)} top-level symbols, {len(source.splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
